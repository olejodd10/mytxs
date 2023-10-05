import datetime
import os
import json
from urllib.parse import unquote

from django import forms
from django.apps import apps
from django.conf import settings as djangoSettings
from django.db import models
from django.db.models import Value as V, Q, Case, When, Min, Max, Sum, ExpressionWrapper, F
from django.db.models.functions import Concat, ExtractMinute, ExtractHour
from django.forms import ValidationError
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.utils.safestring import mark_safe
from django.utils.functional import cached_property

from mytxs import consts
from mytxs import settings as mytxsSettings
from mytxs.fields import BitmapMultipleChoiceField, MyDateField, MyManyToManyField, MyTimeField
from mytxs.utils.formUtils import toolTip
from mytxs.utils.modelCacheUtils import ModelWithStrRep, clearCachedProperty, strDecorator
from mytxs.utils.modelUtils import bareAktiveDecorator, qBool, groupBy, getInstancesForKor, isStemmegruppeVervNavn, korLookup, orderStemmegruppeVerv, validateBruktIKode, validateM2MFieldEmpty, validateStartSlutt, vervInnehavelseAktiv, stemmegruppeVerv
from mytxs.utils.utils import cropImage


class LoggQuerySet(models.QuerySet):
    def getLoggForModelPK(self, model, pk):
        'Gets the most recent logg given a model (which may be a string or an actual model) and a pk'
        if type(model) == str:
            model = apps.get_model('mytxs', model)
        return Logg.objects.filter(model=model.__name__, instancePK=pk).order_by('-timeStamp').first()
    
    def getLoggFor(self, instance):
        'Gets the most recent logg corresponding to the instance'
        return self.getLoggForModelPK(type(instance), instance.pk)

    def getLoggLinkFor(self, instance):
        'get_absolute_url for the most recent logg correpsonding to the instance'
        if logg := self.getLoggFor(instance):
            return logg.get_absolute_url()


class Logg(models.Model):
    objects = LoggQuerySet.as_manager()
    timeStamp = models.DateTimeField(auto_now_add=True)

    kor = models.ForeignKey(
        'Kor',
        related_name='logger',
        on_delete=models.SET_NULL,
        null=True
    )

    author = models.ForeignKey(
        'Medlem',
        on_delete=models.SET_NULL,
        null=True,
        related_name='logger'
    )

    CREATE, UPDATE, DELETE = 1, 0, -1
    CHANGE_CHOICES = ((CREATE, 'Create'), (UPDATE, 'Update'), (DELETE, 'Delete'))
    change = models.SmallIntegerField(choices=CHANGE_CHOICES, null=False)
    
    model = models.CharField(
        max_length=50
    )
    'Dette er model.__name__'

    instancePK = models.PositiveIntegerField(
        null=False
    )

    value = models.JSONField(null=False)
    'Se to_dict i mytxs/signals/logSignals.py'

    strRep = models.CharField(null=False, max_length=100)
    'String representasjon av objektet loggen anngår, altså resultatet av str(obj)'

    def getModel(self):
        return apps.get_model('mytxs', self.model)

    def formatValue(self):
        '''
        Returne oversiktlig json representasjon av objektet, med <a> lenker
        satt inn der det e foreign keys til andre Logg objekt, slik at dette
        fint kan settes direkte inn i en <pre> tag.
        '''
        jsonRepresentation = json.dumps(self.value, indent=4)

        foreignKeyFields = list(filter(lambda field: isinstance(field, models.ForeignKey), self.getModel()._meta.get_fields()))

        lines = jsonRepresentation.split('\n')

        def getLineKey(line):
            return line.split(':')[0].strip().replace('"', '')

        for l in range(len(lines)):
            for foreignKeyField in foreignKeyFields:
                if foreignKeyField.name == getLineKey(lines[l]) and type(self.value[foreignKeyField.name]) == int:
                    relatedLogg = Logg.objects.filter(pk=self.value[foreignKeyField.name]).first()

                    lines[l] = lines[l].replace(f'{self.value[foreignKeyField.name]}', 
                        f'<a href={relatedLogg.get_absolute_url()}>{relatedLogg.strRep}</a>')

        jsonRepresentation = '\n'.join(lines)

        return mark_safe(jsonRepresentation)

    def getReverseRelated(self):
        'Returne en liste av logger som referere (1:1 eller n:1) til denne loggen'
        reverseForeignKeyRels = list(filter(lambda field: isinstance(field, models.ManyToOneRel), self.getModel()._meta.get_fields()))
        foreignKeyFields = list(map(lambda rel: rel.remote_field, reverseForeignKeyRels))
        
        qs = Logg.objects.none()

        for foreignKeyField in foreignKeyFields:
            qs |= Logg.objects.filter(
                Q(**{f'value__{foreignKeyField.name}': self.pk}),
                model=foreignKeyField.model.__name__,
            )

        return qs
    
    def getM2MRelated(self):
        'Skaffe alle m2m logger for denne loggen'
        return groupBy(self.forwardM2Ms.all() | self.backwardM2Ms.all(), 'm2mName')

    def getActual(self):
        'Get the object this Logg is a log of, if it exists'
        return self.getModel().objects.filter(pk=self.instancePK).first()
    
    def getActualUrl(self):
        'get_absolute_url for the object this Logg is a log of, if it exists'
        if actual := self.getActual():
            if hasattr(actual, 'get_absolute_url'):
                return actual.get_absolute_url()

    def nextLogg(self):
        return Logg.objects.filter(
            model=self.model,
            instancePK=self.instancePK,
            timeStamp__gt=self.timeStamp
        ).order_by('timeStamp').first()
    
    def lastLogg(self):
        return Logg.objects.filter(
            model=self.model,
            instancePK=self.instancePK,
            timeStamp__lt=self.timeStamp
        ).order_by('-timeStamp').first()

    def get_absolute_url(self):
        return reverse('logg', args=[self.pk])

    def __str__(self):
        return f'{self.model}{"-*+"[self.change+1]} {self.strRep}'

    class Meta:
        ordering = ['-timeStamp', '-pk']
        verbose_name_plural = 'logger'


class LoggM2M(models.Model):
    timeStamp = models.DateTimeField(auto_now_add=True)

    m2mName = models.CharField(
        max_length=50
    )
    'A string containing the m2m source model name and the m2m field name separated by an underscore'

    author = models.ForeignKey(
        'Medlem',
        on_delete=models.SET_NULL,
        null=True,
        related_name='M2Mlogger'
    )

    fromLogg = models.ForeignKey(
        Logg,
        on_delete=models.CASCADE,
        null=False,
        related_name='forwardM2Ms'
    )

    toLogg = models.ForeignKey(
        Logg,
        on_delete=models.CASCADE,
        null=False,
        related_name='backwardM2Ms'
    )

    CREATE, DELETE = 1, -1
    CHANGE_CHOICES = ((CREATE, 'Create'), (DELETE, 'Delete'))
    change = models.SmallIntegerField(choices=CHANGE_CHOICES, null=False)

    def correspondingM2M(self, forward=True):
        'Gets the corresponding create or delete M2M'
        if self.change == LoggM2M.CREATE:
            return LoggM2M.objects.filter(
                fromLogg__instancePK=self.fromLogg.instancePK,
                toLogg__instancePK=self.toLogg.instancePK,
                m2mName=self.m2mName,
                change=LoggM2M.DELETE,
                timeStamp__gt=self.timeStamp
            ).order_by(
                'timeStamp'
            ).first()
        else:
            return LoggM2M.objects.filter(
                fromLogg__instancePK=self.fromLogg.instancePK,
                toLogg__instancePK=self.toLogg.instancePK,
                m2mName=self.m2mName,
                change=LoggM2M.CREATE,
                timeStamp__lt=self.timeStamp
            ).order_by(
                '-timeStamp'
            ).first()

    def __str__(self):
        return f'{self.m2mName}{"-_+"[self.change+1]} {self.fromLogg.strRep} <-> {self.toLogg.strRep}'

    class Meta:
        ordering = ['-timeStamp', '-pk']


class MedlemQuerySet(models.QuerySet):
    def annotateFulltNavn(self):
        'Annotate deres navn med korrekt mellomrom som "fulltNavn", viktig for søk på medlemmer'
        return self.annotate(
            fulltNavn=Case(
                When(
                    mellomnavn='',
                    then=Concat('fornavn', V(' '), 'etternavn')
                ),
                default=Concat('fornavn', V(' '), 'mellomnavn', V(' '), 'etternavn')
            )
        )

    def annotateKarantenekor(self, kor=None, storkor=False):
        '''
        Annotate året de hadde sitt første stemmegruppe eller dirr verv. 
        Gi kor argumentet for å spesifiser kor, eller gi storkor for å bruk storkor. 
        Merk at man kanskje må refresh querysettet dersom man allerede har filtrert på stemmegruppeverv. 
        '''
        return self.annotate(
            K=Min(
                'vervInnehavelser__start__year',
                filter=
                    stemmegruppeVerv('vervInnehavelser__verv', includeDirr=True) &
                    (korLookup(kor, 'vervInnehavelser__verv__kor') if kor else qBool(True)) &
                    (Q(vervInnehavelser__verv__kor__kortTittel__in=consts.bareStorkorKortTittel) if storkor else qBool(True))
            )
        )

    def filterIkkePermitert(self, kor, dato=None):
        'Returne et queryset av (medlemmer som er aktive) AND (ikke permiterte)'
        if dato == None:
            dato = datetime.datetime.today()

        permiterte = self.filter(
            vervInnehavelseAktiv(dato=dato),
            vervInnehavelser__verv__navn='Permisjon',
            vervInnehavelser__verv__kor=kor
        )

        return self.filter(# Skaff aktive korister...
            vervInnehavelseAktiv(dato=dato),
            stemmegruppeVerv('vervInnehavelser__verv'),
            vervInnehavelser__verv__kor=kor
        ).exclude(# ...som ikke har permisjon
            pk__in=permiterte.values_list('pk', flat=True)
        )
    
    def prefetchVervDekorasjonKor(self):
        return self.prefetch_related('vervInnehavelser__verv__kor', 'dekorasjonInnehavelse__dekorasjon__kor')
    
    def annotateFravær(self, kor):
        'Annotater gyldigFravær, ugyldigFravær og hendelseVarighet'
        def getDateTime(fieldName):
            'Kombinere og returne separate Date og Time felt til ett DateTime felt'
            return ExpressionWrapper(
                F(f'{fieldName}Date') + F(f'{fieldName}Time'),
                output_field=models.DateTimeField()
            )

        hendelseVarighet = ExpressionWrapper(
            ExtractMinute(getDateTime('oppmøter__hendelse__slutt') - getDateTime('oppmøter__hendelse__start')) + 
            ExtractHour(getDateTime('oppmøter__hendelse__slutt') - getDateTime('oppmøter__hendelse__start')) * 60,
            output_field=models.IntegerField()
        )

        today = datetime.date.today()

        filterQ = Q(
            Q(oppmøter__hendelse__startDate__month__gte=7) if today.month >= 7 else Q(oppmøter__hendelse__startDate__month__lt=7),
            korLookup(kor, 'oppmøter__hendelse__kor'),
            oppmøter__hendelse__startDate__year=today.year,
            oppmøter__hendelse__kategori=Hendelse.OBLIG,
            oppmøter__hendelse__startDate__lt=datetime.date.today()
        )

        return self.annotate(
            gyldigFravær = Sum('oppmøter__fravær', default=0, filter=Q(filterQ, oppmøter__gyldig=Oppmøte.GYLDIG)) + 
                Sum(hendelseVarighet, default=0, filter=Q(filterQ, oppmøter__gyldig=Oppmøte.GYLDIG, oppmøter__fravær=None)),
            ugyldigFravær = Sum('oppmøter__fravær', default=0, filter=Q(filterQ, ~Q(oppmøter__gyldig=Oppmøte.GYLDIG))) + 
                Sum(hendelseVarighet, default=0, filter=Q(filterQ, ~Q(oppmøter__gyldig=Oppmøte.GYLDIG),oppmøter__fravær=None)),
            hendelseVarighet = Sum(hendelseVarighet, default=0,filter=filterQ)
        )


class Medlem(ModelWithStrRep):
    objects = MedlemQuerySet.as_manager()

    user = models.OneToOneField(
        djangoSettings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='medlem',
        blank=True
    )

    fornavn = models.CharField(max_length = 50, default='Autogenerert')
    mellomnavn = models.CharField(max_length = 50, default='', blank=True)
    etternavn = models.CharField(max_length = 50, default='Testbruker')

    @property
    def navn(self):
        'Returne navnet med korrekt mellomrom'
        if self.mellomnavn:
            return f'{self.fornavn} {self.mellomnavn} {self.etternavn}'
        else:
            return f'{self.fornavn} {self.etternavn}'

    gammeltMedlemsnummer = models.CharField(max_length=9, default='', blank=True)
    'Formatet for dette er "TSS123456" eller "TKS123456"'

    # Følgende fields er bundet av GDPR, vi må ha godkjennelse fra medlemmet for å lagre de. 
    fødselsdato = MyDateField(null=True, blank=True)
    epost = models.EmailField(max_length=100, blank=True)
    tlf = models.CharField(max_length=20, default='', blank=True)
    studieEllerJobb = models.CharField(max_length=100, blank=True)
    boAdresse = models.CharField(max_length=100, blank=True)
    foreldreAdresse = models.CharField(max_length=100, blank=True)

    sjekkhefteSynlig = BitmapMultipleChoiceField(choicesList=consts.sjekkhefteSynligOptions)

    def generateUploadTo(instance, fileName):
        path = 'sjekkhefteBilder/'
        format = f'{instance.pk}.{fileName.split(".")[-1]}'
        fullPath = os.path.join(path, format)
        return fullPath

    bilde = models.ImageField(upload_to=generateUploadTo, null=True, blank=True)

    ønskerVårbrev = models.BooleanField(default=False)
    død = models.BooleanField(default=False)
    notis = models.TextField(blank=True)

    innstillinger = models.JSONField(null=False, default=dict, editable=False)
    'For å lagre ting som endrer hvordan brukeren ser siden, f.eks. tversAvKor, disableTilganger osv'

    @cached_property
    def aktiveKor(self):
        'Returne kor medlemmet er aktiv i, sortert med storkor først. Ignorerer permisjon.'
        return Kor.objects.filter(
            stemmegruppeVerv(includeDirr=True),
            vervInnehavelseAktiv('verv__vervInnehavelser'),
            verv__vervInnehavelser__medlem=self
        ).orderKor()

    @cached_property
    def firstStemmegruppeVervInnehavelse(self):
        'Returne første stemmegruppeverv de hadde i et storkor'
        return self.vervInnehavelser.filter(
            stemmegruppeVerv(),
            verv__kor__kortTittel__in=['TSS', 'TKS']
        ).order_by('start').first()
    
    @cached_property
    def storkor(self):
        'Returne koran TSS eller TKS eller en tom streng'
        if self.firstStemmegruppeVervInnehavelse:
            return self.firstStemmegruppeVervInnehavelse.verv.kor
        return ''

    @property
    def karantenekor(self):
        'Returne K{to sifret år av første storkor stemmegruppeverv}, eller 4 dersom det e før år 2000'
        if self.firstStemmegruppeVervInnehavelse:
            if self.firstStemmegruppeVervInnehavelse.start.year >= 2000:
                return f'K{self.firstStemmegruppeVervInnehavelse.start.strftime("%y")}'
            else:
                return f'K{self.firstStemmegruppeVervInnehavelse.start.strftime("%Y")}'
        else:
            return ''
    
    @property
    def faktiskeTilganger(self):
        'Returne aktive tilganger, til bruk i addOptionForm som trenger å vite hvilke tilganger du har før innstillinger filtrering'
        return Tilgang.objects.filter(vervInnehavelseAktiv('verv__vervInnehavelser'), verv__vervInnehavelser__medlem=self).distinct()

    @cached_property
    def tilganger(self):
        'Returne aktive tilganger etter å ha filtrert på innstillinger'
        if self.innstillinger.get('disableTilganger', False):
            return Tilgang.objects.none()
        if not self.innstillinger.get('tversAvKor', False):
            return self.faktiskeTilganger.exclude(navn='tversAvKor')
        return self.faktiskeTilganger
    
    @cached_property
    def navBar(self):
        '''
        Dette returne en dict som rekursivt inneheld flere dicts eller True basert på tilganger. Dette ugjør dermed
        hvilke sider i navbar medlemmet får opp, samt hvilke undersider medlemmet får opp. 

        For å sjekke om brukeren har tilgang til en side bruker vi medlem.navBar.[sidenavn] i template eller 
        medlem.navBar.get(sidenavn) i python. Løvnodene er True slik at tilgang til siden skal funke likt med og uten 
        subpages. Om det er ryddigere kan en løvnode settes til False. Den filtreres da bort før vi returne. 
        
        Veldig viktig at dette ikke returne noko som inneheld querysets, for da vil vi hitte databasen veldig mange ganger!
        Dette e også en av få deler av kodebasen som faktisk kjører på alle sider, så fint å optimaliser denne koden 
        så my som mulig mtp databaseoppslag. 
        '''

        def toDict(iterable):
            'Lage en dict av alle element i en iterable, med values True'
            return dict.fromkeys(iterable, True)

        sider = dict()

        # Sjekkheftet
        if self.storkor.kortTittel == 'TKS':
            sider['sjekkheftet'] = toDict(consts.bareKorKortTittelTKSRekkefølge + ['søk', 'jubileum', 'sjekkhefTest'])
        else:
            sider['sjekkheftet'] = toDict(consts.bareKorKortTittel + ['søk', 'jubileum', 'sjekkhefTest'])

        # Sjekkheftet undergrupper
        for sjekkhefteSide in Tilgang.objects.filter(
            ~Q(kor__kortTittel='Sangern'),
            sjekkheftetSynlig=True
        ).values('navn', 'kor__kortTittel'):
            if sider['sjekkheftet'][sjekkhefteSide['kor__kortTittel']] == True:
                sider['sjekkheftet'][sjekkhefteSide['kor__kortTittel']] = {}
            sider['sjekkheftet'][sjekkhefteSide['kor__kortTittel']][sjekkhefteSide['navn']] = True

        # Semesterplan
        if aktiveKor := self.aktiveKor:
            sider['semesterplan'] = toDict(aktiveKor.values_list('kortTittel', flat=True))

        # Øverige
        # Herunder hadd vi gjort mange queries av typen self.tilganger.filter(navn='...').exists()
        # så istedet for å gjør det skaffe vi en liste av tilgangNavnan, og bruke det:)
        tilgangNavn = list(self.tilganger.values_list('navn', flat=True))

        if tilgangNavn:
            sider['loggListe'] = True
        
        if 'tversAvKor' in tilgangNavn:
            sider['medlemListe'] = True
            sider['vervListe'] = True
            sider['dekorasjonListe'] = True
            sider['turneListe'] = True
            sider['tilgangListe'] = True

        if 'medlemsdata' in tilgangNavn:
            sider['medlemListe'] = True

        if 'semesterplan' in tilgangNavn:
            sider['hendelseListe'] = True

        if 'fravær' in tilgangNavn:
            sider['hendelseListe'] = True
            sider['fraværListe'] = toDict(Kor.objects.filter(tilganger__in=self.tilganger.filter(navn='fravær')).values_list('kortTittel', flat=True))

        if 'vervInnehavelse' in tilgangNavn:
            sider['medlemListe'] = True
            sider['vervListe'] = True

        if 'dekorasjonInnehavelse' in tilgangNavn:
            sider['medlemListe'] = True
            sider['dekorasjonListe'] = True

        if 'verv' in tilgangNavn:
            sider['vervListe'] = True

        if 'dekorasjon' in tilgangNavn:
            sider['dekorasjonListe'] = True

        if 'tilgang' in tilgangNavn:
            sider['vervListe'] = True
            sider['tilgangListe'] = True

        if 'turne' in tilgangNavn:
            sider['turneListe'] = True
            sider['medlemListe'] = True

        # Før vi returne, gå over og fjern alle falsy verdier, rekursivt. 
        def removeFalsy(sider):
            for side in sider:
                if not sider[side]:
                    # Om det e falsy, fjern det
                    del sider[side]
                elif isinstance(sider[side], dict):
                    # Fjern falsy children
                    removeFalsy(sider[side])
            if not sider:
                # Om vi fjerna alle children, erstatt den tomme dicten med True
                # Dette fordi å fjern alle undersider ikke betyr at vi skal fjerne en side
                sider[side] = True
        removeFalsy(sider)

        return sider

    def harRedigerTilgang(self, instance):
        '''
        Returne om medlemmet har tilgang til å redigere instansen, både for instances i databasen og ikkje.
        Ikke i databasen e f.eks. når vi har et inlineformset som allerede har satt kor på objektet vi kan create. 
        '''
        if instance.pk:
            # Dersom instansen finnes i databasen
            return self.redigerTilgangQueryset(type(instance)).contains(instance)
        
        if kor := instance.kor:
            # Dersom den ikke finnes, men den vet hvilket kor den havner i
            return Kor.objects.filter(tilganger__in=self.tilganger.filter(navn=consts.modelTilTilgangNavn[type(instance).__name__])).contains(kor)

        # Ellers, return om vi har noen tilgang til den typen objekt
        return self.tilganger.filter(navn=consts.modelTilTilgangNavn[type(instance).__name__]).exists()

    @bareAktiveDecorator
    def redigerTilgangQueryset(self, model, resModel=None, fieldType=None):
        '''
        Returne et queryset av objekter vi har tilgang til å redigere. 
        
        resModel brukes for å si at vi ønske å få instances fra resModel istedet, fortsatt for kor 
        som vi har tilgang til å endre på model. Brukes for å sjekke hvilke relaterte objekter vi kan 
        velge i ModelChoiceField.

        FieldType e enten ModelChoiceField eller ModelMultipleChoiceField, og brukes for å håndter at vi har
        tilgang til ting på tvers av kor når model og resModel stemme. Uten tversAvKor endrer dette ingenting. 
        '''

        # Sett resModel om ikke satt
        if not resModel:
            resModel = model
        
        # Dersom vi prøve å skaff relatert queryset, håndter tversAvKor
        elif self.tilganger.filter(navn='tversAvKor').exists() and model != resModel and (
            # For ModelChoiceField: Sjekk at resModel ikke er modellen som model.kor avhenger av
            # Tenk vervInnehavelse: Med tversAvKor tilgangen skal vi få tilgang til alle medlememr, men ikke alle verv.
            # F.eks. i newForm vil vi få mulighet til å opprette ting på alle kor dersom vi ikke har med default get 'Kor'
            (fieldType == forms.ModelChoiceField and consts.korAvhengerAv.get(model.__name__, 'Kor') != resModel.__name__) or 
            # For ModelMultipleChoiceField: Bare sjekk at det e et ModelMultipleChoiceField. Om vi bruke redigerTilgangQueryset
            # rett model alltid være modellen den som styrer tilgangen på feltet, og om resModel ikke erlik den kan den anntas
            # å være den andre siden. 
            (fieldType == forms.ModelMultipleChoiceField)
        ):
            return resModel.objects.all()

        # Medlem er komplisert, både fordi man har redigeringstilgang på seg sjølv, 
        # og fordi medlem ikke har et enkelt forhold til kor. 
        if model == Medlem:
            # Skaff medlemmer i koret du har tilgangen
            medlemmer = getInstancesForKor(resModel, Kor.objects.filter(tilganger__in=self.tilganger.filter(navn='medlemsdata')))
            
            # Dersom du har tversAvKor, hiv på alle medlemmer uten kor
            if resModel == Medlem and self.tilganger.filter(navn='tversAvKor').exists():
                medlemmer |= Medlem.objects.exclude(
                    stemmegruppeVerv('vervInnehavelser__verv')
                )

            return medlemmer

        # For alle andre modeller, bare skaff objektene for modellen og koret du evt har tilgangen. 
        returnQueryset = getInstancesForKor(resModel, Kor.objects.filter(tilganger__in=self.tilganger.filter(navn=consts.modelTilTilgangNavn[model.__name__])))

        # Exclude Verv og VervInnehavelser som gir tilganger som medlemmet ikke har, dersom medlemmet ikke har tilgang tilgangen 
        # i koret til vervet. Dette hindre at noen med vervInnehavelse tilgangen kan gjøre seg selv til Formann og gå løs på 
        # medlemsregisteret, men fungere også for alle verv som gir tilganger man ikkje selv har. 
        
        if model in [Verv, VervInnehavelse] and resModel in [Verv, VervInnehavelse]:
            if resModel == Verv:
                return returnQueryset.exclude(
                    ~Q(kor__in=self.tilganger.filter(navn='tilgang').values_list('kor', flat=True)),
                    tilganger__in=Tilgang.objects.exclude(pk__in=self.tilganger),
                )
            if resModel == VervInnehavelse:
                return returnQueryset.exclude(
                    ~Q(verv__kor__in=self.tilganger.filter(navn='tilgang').values_list('kor', flat=True)),
                    verv__tilganger__in=Tilgang.objects.exclude(pk__in=self.tilganger), 
                )

        return returnQueryset
    
    def harSideTilgang(self, instance):
        'Returne en boolean som sie om man har tilgang til denne siden'
        return self.sideTilgangQueryset(type(instance)).contains(instance)

    @bareAktiveDecorator
    def sideTilgangQueryset(self, model):
        '''
        Returne queryset av objekt der vi har tilgang til noe på den tilsvarende siden.
        Dette slår altså sammen logikken for 
        1. Hva som kommer opp i lister
        2. Hvilke sider man har tilgang til, og herunder hvilke logger man har tilgang til
        '''

        # Om du har tversAvKor sie vi at du har sidetilgang til alle objekt. Det e en overforenkling som unødvendig også 
        # gir sideTilgang til f.eks. andre kor sine tilgang sider, men det gjør at denne koden bli ekstremt my enklar.
        # Alternativt hadd vi måtta skrevet "Om du har tversAvKor tilgangen i samme kor som en tilgang til en relasjon
        # til andre objekt, har du tilgang til alle andre slike objekter.", som e veldig vanskelig å uttrykke godt. Vi kan prøv å 
        # fiks dette i framtiden om vi orke og ser behov for det. E gjør ikke det no. 

        # Dette gjør også at de eneste som kan styre med folk som ikke har kor er korlederne, som virke fair. 
        if self.tilganger.filter(navn='tversAvKor').exists():
            return model.objects.all()
        
        # For Logg sjekke vi bare om du har tilgang til modellen og koret loggen refererer til
        if model == Logg:
            loggs = Logg.objects.none()
            for loggedModel in consts.getLoggedModels():
                loggs |= Logg.objects.filter(
                    Q(model=loggedModel.__name__, instancePK__in=self.redigerTilgangQueryset(loggedModel).values_list('id', flat=True)) | 
                    Q(model=None)
                )
            return loggs

        # Du har tilgang til sider (som medlem) der du kan endre et relatert form (som vervInnehavelse, dekorasjonInnehavelse eller turneer). 
        # Dette kunna vi åpenbart automatisert meir, men e like slik det e no. Med full automatisering med modelUtils.getAllRelatedModels 
        # hadd f.eks. folk med tilgang til oppmøter hatt tilgang til alle medlemmer, som ikkje stemme overrens med siden. 
        # Det er trygt å returne dette siden det alltid vil være likt redigerTilgangQueryset eller større (trur e)
        for sourceModel, relatedModel in consts.modelWithRelated.items():
            if (
                (model.__name__ == sourceModel) and \
                (relatedTilgang := [consts.modelTilTilgangNavn[m] for m in relatedModel]) and \
                (relaterteTilganger := self.tilganger.filter(navn__in=relatedTilgang))
            ):
                return getInstancesForKor(model, Kor.objects.filter(tilganger__in=relaterteTilganger)) | self.redigerTilgangQueryset(model)

        # Forøverig, return de sidene der du kan redigere sidens instans
        return self.redigerTilgangQueryset(model)

    @property
    def kor(self):
        return self.storkor or None if self.pk else None
    
    def get_absolute_url(self):
        return reverse('medlem', args=[self.pk])
    
    affectedBy = ['VervInnehavelse']
    @strDecorator
    def __str__(self):
        clearCachedProperty(self, 'firstStemmegruppeVervInnehavelse', 'storkor')
        if self.pk and (storkor := self.storkor):
            return f'{self.navn} {storkor} {self.karantenekor}'
        return self.navn
    
    class Meta:
        ordering = ['fornavn', 'mellomnavn', 'etternavn', '-pk']
        verbose_name_plural = 'medlemmer'

    def save(self, *args, **kwargs):
        # Crop bildet om det har endret seg
        if self.pk and self.bilde and self.bilde != Medlem.objects.get(pk=self.pk).bilde:
            self.bilde = cropImage(self.bilde, self.bilde.name, 270, 330)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        validateM2MFieldEmpty(self, 'turneer')
        super().delete(*args, **kwargs)


class KorQuerySet(models.QuerySet):
    def orderKor(self, tksRekkefølge=False):
        'Sorter kor på storkor først og deretter på kjønnsfordeling'
        return self.order_by(Case(
            *[When(kortTittel=kor, then=i) for i, kor in 
                (enumerate(consts.bareKorKortTittel if not tksRekkefølge else consts.bareKorKortTittelTKSRekkefølge))
            ]
        ))


class Kor(models.Model):
    objects = KorQuerySet.as_manager()

    kortTittel = models.CharField(max_length=10)
    langTittel = models.CharField(max_length=50)
    stemmefordeling = models.CharField(choices=[(sf, sf) for sf in ['SA', 'TB', 'SATB', '']], default='', blank=True)

    # Dropper å drive med strRep her, blir bare overhead for ingen fortjeneste
    def __str__(self):
        return self.kortTittel
    
    class Meta:
        verbose_name_plural = 'kor'


class Verv(ModelWithStrRep):
    navn = models.CharField(max_length=50)

    kor = models.ForeignKey(
        Kor,
        related_name='verv',
        on_delete=models.DO_NOTHING,
        null=True
    )

    bruktIKode = models.BooleanField(
        default=False, 
        help_text=toolTip('Hvorvidt vervet er brukt i kode og følgelig ikke kan endres på av brukere.')
    )

    @cached_property
    def stemmegruppeVerv(self):
        return isStemmegruppeVervNavn(self.navn)

    def get_absolute_url(self):
        return reverse('verv', args=[self.kor.kortTittel, self.navn])

    @strDecorator
    def __str__(self):
        return f'{self.navn}({self.kor.__str__()})'
    
    class Meta:
        unique_together = ('navn', 'kor')
        ordering = ['kor', orderStemmegruppeVerv(), 'navn']
        verbose_name_plural = 'verv'

    def clean(self, *args, **kwargs):
        validateBruktIKode(self)
    
    def delete(self, *args, **kwargs):
        validateM2MFieldEmpty(self, 'tilganger')
        super().delete(*args, **kwargs)


class VervInnehavelse(ModelWithStrRep):
    medlem = models.ForeignKey(
        Medlem,
        on_delete=models.PROTECT,
        null=False,
        related_name='vervInnehavelser'
    )
    verv = models.ForeignKey(
        Verv,
        on_delete=models.PROTECT,
        null=False,
        related_name='vervInnehavelser'
    )
    start = MyDateField(blank=False)
    slutt = MyDateField(blank=True, null=True)
    
    @property
    def aktiv(self):
        return self.start <= datetime.date.today() and (self.slutt == None or datetime.date.today() <= self.slutt)

    @property
    def kor(self):
        return self.verv.kor if self.verv_id else None
    
    affectedByStrRep = ['Medlem', 'Verv']
    @strDecorator
    def __str__(self):
        return f'{self.medlem.__str__()} -> {self.verv.__str__()}'
    
    class Meta:
        unique_together = ('medlem', 'verv', 'start')
        ordering = ['-start', '-slutt', '-pk']
        verbose_name_plural = 'vervinnehavelser'

    def clean(self, *args, **kwargs):
        validateStartSlutt(self)
        # Valider at dette medlemmet ikke har dette vervet i samme periode med en annen vervInnehavelse.
        if hasattr(self, 'verv'):
            if self.verv.stemmegruppeVerv:
                if VervInnehavelse.objects.filter(
                    ~Q(pk=self.pk),
                    stemmegruppeVerv(),
                    ~(Q(slutt__isnull=False) & Q(slutt__lt=self.start)),
                    ~qBool(self.slutt, trueOption=Q(start__gt=self.slutt)),
                    verv__kor=self.kor,
                    medlem=self.medlem,
                ).exists():
                    raise ValidationError(
                        _('Kan ikke ha flere stemmegruppeverv i samme kor samtidig'),
                        code='overlappingVervInnehavelse'
                    )
            else:
                if VervInnehavelse.objects.filter(
                    ~Q(pk=self.pk),
                    ~(Q(slutt__isnull=False) & Q(slutt__lt=self.start)),
                    ~qBool(self.slutt, trueOption=Q(start__gt=self.slutt)),
                    medlem=self.medlem,
                    verv=self.verv,
                ).exists():
                    raise ValidationError(
                        _('Kan ikke ha flere vervInnehavelser av samme verv samtidig'),
                        code='overlappingVervInnehavelse'
                    )

    def save(self, *args, **kwargs):
        self.clean()

        oldSelf = VervInnehavelse.objects.filter(pk=self.pk).first()

        super().save(*args, **kwargs)

        # Oppdater hvilke oppmøter man har basert på stemmegruppeVerv og permisjon

        # Per no ser e ikkje en ryddigar måte å gjør dette på, enn å bare prøv å minimer antall 
        # hendelser vi calle save metoden på. Det e vanskelig å skaff hvilke hendelser 
        # som blir lagt til og fjernet av en endring av varighet eller type av verv. Sammenlign
        # - "Medlemmer som har aktive stemmegruppeverv som ikke har permisjon den dagen."
        # - "Hendelsene som faller på dager der vi har endret et permisjon/stemmegruppeverv, 
        # eller dager vi ikke har endret dersom vi endrer typen verv."
        if self.verv.stemmegruppeVerv or self.verv.navn == 'Permisjon' or \
            (oldSelf and (oldSelf.verv.stemmegruppeVerv or oldSelf.verv.navn == 'Permisjon')):

            hendelser = Hendelse.objects.filter(kor=self.verv.kor)
            
            if not oldSelf:
                # Om ny vervInnehavelse, save på alle hendelser i varigheten
                hendelser.saveAllInPeriod(self.start, self.slutt)

            elif self.verv.stemmegruppeVerv != oldSelf.verv.stemmegruppeVerv or \
                self.verv.navn == 'Permisjon' != oldSelf.verv.navn == 'Permisjon':
                # Om vi bytte hvilken type verv det er, save alle hendelser i hele perioden
                hendelser.saveAllInPeriod(self.start, self.slutt, oldSelf.start, oldSelf.slutt)

            elif (self.verv.stemmegruppeVerv and oldSelf.verv.stemmegruppeVerv) or \
                (self.verv.navn == 'Permisjon' and oldSelf.verv.navn == 'Permisjon'):
                # Om vi ikke bytte hvilken type verv det er, save hendelser som er 
                # mellom start og start, og mellom slutt og slutt

                if oldSelf.start != self.start:
                    # Start av verv er aldri None
                    hendelser.saveAllInPeriod(self.start, oldSelf.start)

                if oldSelf.slutt != self.slutt:
                    if oldSelf.slutt != None and self.slutt != None:
                        # Om verken e None, lagre som vanlig
                        hendelser.saveAllInPeriod(self.slutt, oldSelf.slutt)
                    else:
                        hendelser.saveAllInPeriod(self.slutt, oldSelf.slutt)
    
    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)

        # Om vi sletter vervInnehavelsen, save alle i varigheten
        if self.verv.stemmegruppeVerv or self.verv.navn == 'Permisjon':
            Hendelse.objects.filter(kor=self.verv.kor).saveAllInPeriod(self.start, self.slutt)


class Tilgang(ModelWithStrRep):
    navn = models.CharField(max_length=50)

    kor = models.ForeignKey(
        Kor,
        related_name='tilganger',
        on_delete=models.DO_NOTHING,
        null=True
    )

    verv = MyManyToManyField(
        Verv,
        related_name='tilganger',
        blank=True
    )

    beskrivelse = models.CharField(
        max_length=200, 
        default='',
        blank=True
    )

    bruktIKode = models.BooleanField(
        default=False, 
        help_text=toolTip('Hvorvidt tilgangen er brukt i kode og følgelig ikke kan endres på av brukere.')
    )

    sjekkheftetSynlig = models.BooleanField(
        default=False,
        help_text=toolTip('Om de som har denne tilgangen skal vises som en gruppe i sjekkheftet.')
    )

    def get_absolute_url(self):
        return reverse('tilgang', args=[self.kor.kortTittel, self.navn])

    @strDecorator
    def __str__(self):
        if self.kor:
            return f'{self.kor.kortTittel}-{self.navn}'
        return self.navn

    class Meta:
        unique_together = ('kor', 'navn')
        ordering = ['kor', 'navn']
        verbose_name_plural = 'tilganger'

    def clean(self, *args, **kwargs):
        validateBruktIKode(self)

    def delete(self, *args, **kwargs):
        validateM2MFieldEmpty(self, 'verv')
        super().delete(*args, **kwargs)


class Dekorasjon(ModelWithStrRep):
    navn = models.CharField(max_length=30)
    kor = models.ForeignKey(
        Kor,
        related_name='dekorasjoner',
        on_delete=models.DO_NOTHING,
        null=True
    )

    def get_absolute_url(self):
        return reverse('dekorasjon', args=[self.kor.kortTittel, self.navn])

    @strDecorator
    def __str__(self):
        return f'{self.navn}({self.kor.__str__()})'
    
    class Meta:
        unique_together = ('navn', 'kor')
        ordering = ['kor', 'navn']
        verbose_name_plural = 'dekorasjoner'


class DekorasjonInnehavelse(ModelWithStrRep):
    medlem = models.ForeignKey(
        Medlem,
        on_delete=models.PROTECT,
        null=False,
        related_name='dekorasjonInnehavelse'
    )
    dekorasjon = models.ForeignKey(
        Dekorasjon,
        on_delete=models.PROTECT,
        null=False,
        related_name='dekorasjonInnehavelse'
    )
    start = MyDateField(null=False)
    
    @property
    def kor(self):
        return self.dekorasjon.kor if self.dekorasjon_id else None
    
    affectedByStrRep = ['Medlem', 'Dekorasjon']
    @strDecorator
    def __str__(self):
        return f'{self.medlem.__str__()} -> {self.dekorasjon.__str__()}'
    
    class Meta:
        unique_together = ('medlem', 'dekorasjon', 'start')
        ordering = ['-start', '-pk']
        verbose_name_plural = 'dekorasjoninnehavelser'


class Turne(ModelWithStrRep):
    navn = models.CharField(max_length=30)
    kor = models.ForeignKey(
        Kor,
        related_name='turneer',
        on_delete=models.DO_NOTHING,
        null=True
    )

    start = MyDateField(null=False)
    slutt = MyDateField(null=True, blank=True)

    beskrivelse = models.TextField(blank=True)

    medlemmer = MyManyToManyField(
        Medlem,
        related_name='turneer',
        blank=True
    )

    def get_absolute_url(self):
        return reverse('turne', args=[self.kor.kortTittel, self.start.year, self.navn])

    @strDecorator
    def __str__(self):
        if self.kor:
            return f'{self.navn}({self.kor.kortTittel}, {self.start.year})'
        return self.navn

    class Meta:
        unique_together = ('kor', 'navn', 'start')
        ordering = ['kor', '-start', 'navn']
        verbose_name_plural = 'turneer'
    
    def clean(self, *args, **kwargs):
        validateStartSlutt(self)

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        validateM2MFieldEmpty(self, 'medlemmer')
        super().delete(*args, **kwargs)


class HendelseQuerySet(models.QuerySet):
    def generateICal(self, medlemPK):
        'Returne en (forhåpentligvis) rfc5545 kompatibel string'
        iCalString= f'''\
BEGIN:VCALENDAR
PRODID:-//mytxs.samfundet.no//MyTXS semesterplan//
VERSION:2.0
CALSCALE:GREGORIAN
METHOD:PUBLISH
X-WR-CALNAME:MyTXS 2.0 semesterplan
X-WR-CALDESC:Denne kalenderen ble generert av MyTXS {
datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S')}Z
X-WR-TIMEZONE:Europe/Oslo
BEGIN:VTIMEZONE
TZID:Europe/Oslo
X-LIC-LOCATION:Europe/Oslo
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE
{''.join(map(lambda h: h.getVevent(medlemPK), self))}END:VCALENDAR\n'''

        # Split lines som e lenger enn 75 characters over fleir linja
        iCalLines = iCalString.split('\n')
        l = 0
        while l < len(iCalLines):
            if len(iCalLines[l]) > 75:
                iCalLines.insert(l+1, ' ' + iCalLines[l][75:])
                iCalLines[l] = iCalLines[l][:75]
            l += 1
        iCalString = '\n'.join(iCalLines)

        # Erstatt alle newlines med CRLF
        iCalString = iCalString.replace('\n', '\r\n')

        return iCalString
    
    def saveAllInPeriod(self, *dates):
        '''
        Utility method for å gjøre koden for lagring av vervInnehavelser enklere,
        dates argumentet kan inneholde datoer eller None, i hvilken som helst rekkefølge.
        '''

        if len(dates) > 0:
            if None in dates:
                datesWithoutNone = [*filter(lambda d: d != None, dates)]
                hendelser = self.filter(startDate__gte=min(datesWithoutNone))
            else:
                hendelser = self.filter(startDate__gte=min(dates), startDate__lte=max(dates))
            for hendelse in hendelser:
                hendelse.save()

    def filterSemester(self):
        'Filtrere og returne bare hendelser for dette semesteret, enten januar-juni eller juli-desember'
        today = datetime.date.today()
        if today.month >= 7:
            return self.filter(
                startDate__year=today.year,
                startDate__month__gte=7
            )
        else:
            return self.filter(
                startDate__year=today.year,
                startDate__month__lt=7
            )


class Hendelse(ModelWithStrRep):
    objects = HendelseQuerySet.as_manager()

    navn = models.CharField(max_length=60)
    beskrivelse = models.CharField(blank=True, max_length=150)
    sted = models.CharField(blank=True, max_length=50)

    kor = models.ForeignKey(
        'Kor',
        related_name='hendelser',
        on_delete=models.SET_NULL,
        null=True
    )

    # Oblig e aktiv avmelding
    # Påmelding e aktiv påmelding
    # Frivilling e uten føring av oppmøte/fravær
    OBLIG, PÅMELDING, FRIVILLIG = 'O', 'P', 'F'
    KATEGORI_CHOICES = ((OBLIG, 'Oblig'), (PÅMELDING, 'Påmelding'), (FRIVILLIG, 'Frivillig'))
    kategori = models.CharField(max_length=1, choices=KATEGORI_CHOICES, null=False, blank=False, default=OBLIG, help_text=toolTip('Ikke endre dette uten grunn!'))

    startDate = MyDateField(blank=False, help_text=toolTip(\
        'Oppmøtene for hendelsen, altså for fraværsføring og fraværsmelding, ' + 
        'genereres av hvilke medlemmer som er aktive i koret på denne datoen, ' + 
        'og ikke har permisjon'))
    startTime = MyTimeField(blank=True, null=True)

    sluttDate = MyDateField(blank=True, null=True)
    sluttTime = MyTimeField(blank=True, null=True)

    @property
    def start(self):
        'Start av hendelsen som datetime eller date'
        if self.startTime:
            return datetime.datetime.combine(self.startDate, self.startTime)
        return self.startDate

    @property
    def slutt(self):
        'Slutt av hendelsen som datetime, date eller None'
        if self.sluttTime:
            return datetime.datetime.combine(self.sluttDate, self.sluttTime)
        return self.sluttDate

    @property
    def varighet(self):
        return int((self.slutt - self.start).total_seconds() // 60) if self.sluttTime else None

    def getVeventStart(self):
        if self.startTime:
            return self.start.strftime('%Y%m%dT%H%M%S')
        return self.start.strftime('%Y%m%d')

    def getVeventSlutt(self):
        if self.sluttTime:
            return self.slutt.strftime('%Y%m%dT%H%M%S')
        if self.sluttDate:
            # I utgangspunktet er slutt tiden (hovedsakling tidspunktet) ekskludert i ical formatet, 
            # men følgelig om det er en sluttdato (uten tid), vil det vises som en dag for lite
            # i kalenderapplikasjonene. Derfor hive vi på en dag her, så det vises rett:)
            return (self.slutt + datetime.timedelta(days=1)).strftime('%Y%m%d')
        return None

    def getVevent(self, medlemPK):
        vevent = 'BEGIN:VEVENT\n'
        vevent += f'UID:{self.kor}-{self.pk}@mytxs.samfundet.no\n'

        if self.kategori == Hendelse.OBLIG:
            vevent += f'SUMMARY:[OBLIG]: {self.navn}\n'
        elif self.kategori == Hendelse.PÅMELDING:
            vevent += f'SUMMARY:[PÅMELDING]: {self.navn}\n'
        else:
            vevent += f'SUMMARY:{self.navn}\n'

        vevent += f'DESCRIPTION:{self.beskrivelse}'
        if self.kategori != Hendelse.FRIVILLIG:
            if self.beskrivelse:
                vevent += '\\n\\n'
            vevent += mytxsSettings.ALLOWED_HOSTS[0] + unquote(reverse('meldFravær', args=[medlemPK, self.pk]))

        vevent += '\n'

        vevent += f'LOCATION:{self.sted}\n'

        if self.startTime:
            vevent += f'DTSTART;TZID=Europe/Oslo:{self.getVeventStart()}\n'
        else:
            vevent += f'DTSTART;VALUE=DATE:{self.getVeventStart()}\n'

        if slutt := self.getVeventSlutt():
            if self.sluttTime:
                vevent += f'DTEND;TZID=Europe/Oslo:{slutt}\n'
            else:
                vevent += f'DTEND;VALUE=DATE:{slutt}\n'
        
        vevent += f'DTSTAMP:{datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")}Z\n'
        vevent += 'END:VEVENT\n'
        return vevent
    
    @property
    def medlemmer(self):
        'Dette gir deg basert på stemmegruppeverv og permisjon, hvilke medlemmer som forventes å dukke opp på hendelsen'
        if self.kategori == Hendelse.FRIVILLIG:
            return Medlem.objects.none()
        return Medlem.objects.filterIkkePermitert(kor=self.kor, dato=self.startDate)

    def getStemmeFordeling(self):
        'Returne stemmefordelingen på en hendelse, basert på Oppmøte.KOMMER.'
        stemmefordeling = {}

        satbStemmer = self.kor.stemmefordeling
        for stemme in satbStemmer:
            for i in '12':
                stemmefordeling[i+stemme] = VervInnehavelse.objects.filter(
                    vervInnehavelseAktiv('', dato=self.startDate),
                    stemmegruppeVerv(),
                    medlem__oppmøter__hendelse=self,
                    verv__kor=self.kor,
                    medlem__oppmøter__ankomst=Oppmøte.KOMMER,
                    verv__navn__endswith=i+stemme
                ).count()
        return stemmefordeling
    
    @property
    def defaultAnkomst(self):
        if self.kategori == Hendelse.OBLIG:
            return Oppmøte.KOMMER
        return Oppmøte.KOMMER_KANSKJE
    
    def get_absolute_url(self):
        return reverse('hendelse', args=[self.pk])

    @strDecorator
    def __str__(self):
        return f'{self.navn}({self.startDate})'

    class Meta:
        unique_together = ('kor', 'navn', 'startDate')
        ordering = ['startDate', 'startTime', 'navn', 'kor']
        verbose_name_plural = 'hendelser'

    def clean(self, *args, **kwargs):
        # Validering av start og slutt
        if not self.sluttDate:
            if self.sluttTime:
                raise ValidationError(
                    _('Kan ikke ha sluttTime uten sluttDate'),
                    code='timeWithoutDate'
                )
        else:
            if bool(self.startTime) != bool(self.sluttTime): # Dette er XOR
                raise ValidationError(
                    _('Må ha både startTime og sluttTime eller verken'),
                    code='startAndEndTime'
                )
            
            validateStartSlutt(self, canEqual=False)

        # Sjekk at varigheten på en obligatorisk hendelse ikke e meir enn 12 timer
        if self.kategori == Hendelse.OBLIG and 720 < (self.varighet or 0):
            raise ValidationError(
                _('En obligatorisk hendelse kan ikke vare lengere enn 12 timer'),
                code='tooLongDuration'
            )

        # Herunder kjem validering av relaterte oppmøter, om den ikkje e lagret ennå, skip dette
        if not self.pk:
            return
        
        if self.oppmøter.filter(fravær__isnull=False).exists() and self.varighet == None:
            raise ValidationError(
                _(f'Kan ikke ha fravær på en hendelse uten varighet'),
                code='fraværUtenVarighet'
            )

        # Sjekk at hendelsen vare lenger enn det største fraværet
        if (self.varighet or 0) < (self.oppmøter.filter(fravær__isnull=False).aggregate(Max('fravær')).get('fravær__max') or 0):
            raise ValidationError(
                _(f'Å lagre dette vil føre til at noen får mere fravær enn varigheten av hendelsen.'),
                code='merFraværEnnHendelse'
            )
    
    def save(self, *args, **kwargs):
        self.clean()

        oldSelf = Hendelse.objects.filter(pk=self.pk).first()

        # Fiksing av relaterte oppmøter
        super().save(*args, **kwargs)
        
        # Legg til oppmøter som skal være der
        for medlem in self.medlemmer.filter(~Q(oppmøter__hendelse=self)):
            self.oppmøter.create(medlem=medlem, hendelse=self, ankomst=self.defaultAnkomst)
        
        if oldSelf:
            # Slett oppmøter som ikke skal være der (og ikke har noen informasjon assosiert med seg)
            self.oppmøter.filter(
                ~Q(medlem__in=self.medlemmer),
                fravær__isnull=True,
                ankomst=oldSelf.defaultAnkomst,
                melding=''
            ).delete()

            # Bytt resten av oppmøtene sin ankomst til default ankomsten, dersom de ikke har en medling. 
            if self.defaultAnkomst != oldSelf.defaultAnkomst:
                for oppmøte in self.oppmøter.filter(melding=''):
                    oppmøte.ankomst = self.defaultAnkomst
                    oppmøte.save()


class OppmøteQueryset(models.QuerySet):
    def annotateHendelseVarighet(self):
        'Annotate varighet av den relaterte hendelsen i minutt som hendelse__varighet'
        # Ja, dette fungerer bare for hendelser som ikke varer mer enn 24 timer, men vi validerer det på hendelse.clean:)
        return self.alias(
            hendelse__startDateTime=ExpressionWrapper(
                F('hendelse__startDate') + F('hendelse__startTime'),
                output_field=models.DateTimeField()
            ),
            hendelse__sluttDateTime=ExpressionWrapper(
                F('hendelse__sluttDate') + F('hendelse__sluttTime'),
                output_field=models.DateTimeField()
            )
        ).annotate(
            hendelse__varighet=ExtractMinute(
                F('hendelse__sluttDateTime') - F('hendelse__startDateTime')
            ) + ExtractHour(
                F('hendelse__sluttDateTime') - F('hendelse__startDateTime')
            ) * 60
        )
    
    def filterSemester(self):
        'Filtrere og returne bare oppmøter for dette semesteret, enten januar-juni eller juli-desember'
        today = datetime.date.today()
        if today.month >= 7:
            return self.filter(
                hendelse__startDate__year=today.year,
                hendelse__startDate__month__gte=7
            )
        else:
            return self.filter(
                hendelse__startDate__year=today.year,
                hendelse__startDate__month__lt=7
            )


class Oppmøte(ModelWithStrRep):
    objects = OppmøteQueryset.as_manager()

    medlem = models.ForeignKey(
        Medlem,
        on_delete=models.CASCADE,
        null=False,
        related_name='oppmøter'
    )

    hendelse = models.ForeignKey(
        Hendelse,
        on_delete=models.CASCADE,
        null=False,
        related_name='oppmøter'
    )

    fravær = models.PositiveSmallIntegerField(null=True, blank=True)
    'Om fravær er None tolkes det som ikke møtt'

    GYLDIG, IKKE_BEHANDLET, UGYLDIG = True, None, False
    GYLDIG_CHOICES = ((GYLDIG, 'Gyldig'), (IKKE_BEHANDLET, 'Ikke behandlet'), (UGYLDIG, 'Ugyldig'))
    gyldig = models.BooleanField(null=True, blank=True, choices=GYLDIG_CHOICES, default=IKKE_BEHANDLET)
    'Om minuttene du hadde av fravær var gyldige'

    @property
    def minutterBorte(self):
        if self.fravær == None:
            return self.hendelse.varighet
        return self.fravær

    KOMMER, KOMMER_KANSKJE, KOMMER_IKKE = True, None, False
    ANKOMST_CHOICES = ((KOMMER, 'Kommer'), (KOMMER_KANSKJE, 'Kommer kanskje'), (KOMMER_IKKE, 'Kommer ikke'))
    ankomst = models.BooleanField(null=True, blank=True, choices=ANKOMST_CHOICES, default=KOMMER_KANSKJE)

    melding = models.TextField(blank=True)

    @property
    def kor(self):
        return self.hendelse.kor if self.pk else None
    
    def get_absolute_url(self):
        return reverse('meldFravær', args=[self.medlem.pk, self.hendelse.pk])

    affectedByStrRep = ['Hendelse', 'Medlem']
    @strDecorator
    def __str__(self):
        if self.hendelse.kategori == Hendelse.OBLIG:
            return f'Fraværssøknad {self.medlem} -> {self.hendelse}'
        elif self.hendelse.kategori == Hendelse.PÅMELDING:
            return f'Påmelding {self.medlem} -> {self.hendelse}'
        else:
            return f'Oppmøte {self.medlem} -> {self.hendelse}'

    class Meta:
        unique_together = ('medlem', 'hendelse')
        ordering = ['-hendelse', 'medlem']
        verbose_name_plural = 'oppmøter'

    def clean(self, *args, **kwargs):
        # Valider mengden fravær
        if self.fravær != None and self.hendelse.varighet == None:
            raise ValidationError(
                _(f'Kan ikke ha fravær på en hendelse uten varighet'),
                code='fraværUtenVarighet'
            )
        
        if self.fravær and self.fravær > (self.hendelse.varighet or 0):
            raise ValidationError(
                _('Kan ikke ha mere fravær enn varigheten av hendelsen.'),
                code='merFraværEnnHendelse'
            )
        
        if self.hendelse.kategori == Hendelse.OBLIG and self.hendelse.defaultAnkomst != self.ankomst and self.melding == '':
            raise ValidationError(
                _('Kan ikke ha en spesiell ankomst på en oblig hendelse uten å skrive en melding'),
                code='ankomstUtenMelding'
            )

    def save(self, *args, **kwargs):
        self.clean()

        oldSelf = Oppmøte.objects.filter(pk=self.pk).first()

        # Dersom melding har endret seg, og gyldig er Ugyldig, endre gyldig til Ikke behandlet.
        if oldSelf and self.gyldig == Oppmøte.UGYLDIG and oldSelf.melding != self.melding:
            self.gyldig = Oppmøte.IKKE_BEHANDLET
        
        super().save(*args, **kwargs)


class Lenke(ModelWithStrRep):
    navn = models.CharField(max_length=255)
    lenke = models.CharField(max_length=255)
    synlig = models.BooleanField(default=False, help_text=toolTip('Om denne lenken skal være synlig på MyTXS'))
    redirect = models.BooleanField(default=False, help_text=toolTip('Om denne lenken skal kunne redirectes til'))

    @property
    def redirectUrl(self):
        if self.pk and self.redirect:
            return 'http://' + mytxsSettings.ALLOWED_HOSTS[0] + reverse('lenkeRedirect', args=[self.kor.kortTittel, self.navn])

    kor = models.ForeignKey(
        'Kor',
        related_name='lenker',
        on_delete=models.SET_NULL,
        null=True
    )

    @strDecorator
    def __str__(self):
        return f'{self.navn}({self.kor})'
    
    class Meta:
        unique_together = ('kor', 'navn', 'lenke')
        ordering = ['kor', 'navn', '-pk']
        verbose_name_plural = 'lenker'
