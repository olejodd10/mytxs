import datetime

from django.core.management.base import BaseCommand
from django.db.models import Exists, OuterRef

from mytxs.models import Logg, Medlem, Oppmøte
from mytxs.utils.modelUtils import stemmegruppeVerv, vervInnehavelseAktiv
from mytxs.utils.utils import getHalvårStart


class Command(BaseCommand):
    def handle(self, *args, **options):
        # Skaff oppmøtene til sluttede korister
        sluttedeKoristerOppmøter = Oppmøte.objects.exclude(
            Exists(Medlem.objects.filter(
                vervInnehavelseAktiv(),
                stemmegruppeVerv('vervInnehavelser__verv', includeDirr=True),
                vervInnehavelser__verv__kor__pk=OuterRef('hendelse__kor'),
                oppmøter=OuterRef('pk')
            ))
        )

        # Slett logger
        Logg.objects.filter(model=Oppmøte.__name__, instancePK__in=sluttedeKoristerOppmøter).delete()

        # Slett oppmøtene
        sluttedeKoristerOppmøter.delete()

        # Skaff oppmøter fra tidligere semestre
        tidligereSemestreOppmøter = Oppmøte.objects.filter(medlem__pk=13642).filter(
            hendelse__startDate__lt=getHalvårStart()
        )

        # Slett logger
        Logg.objects.filter(model=Oppmøte.__name__, instancePK__in=tidligereSemestreOppmøter).delete()

        # Slett fraværsmeldingan
        tidligereSemestreOppmøter.update(melding='')
