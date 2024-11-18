import { MIDI, PLAYER, SCORE } from './constants.js';

export function uiCreateMasterUi(songDuration, songBars, progressCallback, barNumberCallback, tempoBarCallback, pauseCallback, loopStartCallback, loopEndCallback, loopActiveCallback) {
    const uiDiv = document.createElement("div");
    uiDiv.id = "uiDiv";

    const progressSpan = document.createElement("span");
    progressSpan.innerText = usToMinSec(0);
    progressSpan.id = "progressSpan";
    uiDiv.appendChild(progressSpan);

    const durationSpan = document.createElement("span");
    durationSpan.innerText = "".concat(" / ", usToMinSec(songDuration));
    uiDiv.appendChild(durationSpan);

    const progressBar = document.createElement("input");
    progressBar.type = "range";
    progressBar.id = "progressBar";
    progressBar.min = 0;
    progressBar.max = songDuration;
    progressBar.value = 0;
    progressBar.oninput = progressCallback;
    uiDiv.appendChild(progressBar);

    const barLabel = document.createElement("label");
    barLabel.innerText = "Bar";
    uiDiv.appendChild(barLabel);

    const barNumber = document.createElement("input");
    barNumber.type = "number";
    barNumber.id = "barNumber";
    barNumber.min = 0; // 1?
    barNumber.max = songBars;
    barNumber.value = 0;
    barNumber.oninput = barNumberCallback;
    uiDiv.appendChild(barNumber);

    const tempoLabel = document.createElement("label");
    tempoLabel.innerText = "Tempo";
    uiDiv.appendChild(tempoLabel);

    const tempoBar = document.createElement("input");
    tempoBar.type = "range";
    tempoBar.min = PLAYER.TEMPO.MIN;
    tempoBar.max = PLAYER.TEMPO.MAX;
    tempoBar.value = PLAYER.TEMPO.DEFAULT;
    tempoBar.step = PLAYER.TEMPO.STEP;
    tempoBar.oninput = tempoBarCallback;
    uiDiv.appendChild(tempoBar);

    // TODO
    // let volumeLabel = document.createElement("label");
    // volumeLabel.innerText = "Master volume";
    // uiDiv.appendChild(volumeLabel);

    // let volumeSlider = document.createElement("input");
    // volumeSlider.type = "range";
    // volumeSlider.min = 0;
    // volumeSlider.max = 100;
    // volumeSlider.value = 50;
    // uiDiv.appendChild(volumeSlider);

    const pauseButton = document.createElement("button");
    pauseButton.innerText = "Play";
    pauseButton.onclick = pauseCallback;
    uiDiv.appendChild(pauseButton);

    const loopLabel = document.createElement("label");
    loopLabel.innerText = "Looping";
    uiDiv.appendChild(loopLabel);

    const loopStartNumber = document.createElement("input");
    loopStartNumber.type = "number";
    loopStartNumber.min = 0;
    loopStartNumber.max = songBars;
    loopStartNumber.value = 0;
    loopStartNumber.oninput = loopStartCallback;
    uiDiv.appendChild(loopStartNumber);

    const loopEndNumber = document.createElement("input");
    loopEndNumber.type = "number";
    loopEndNumber.min = 0;
    loopEndNumber.max = songBars;
    loopEndNumber.value = songBars;
    loopEndNumber.oninput = loopEndCallback;
    uiDiv.appendChild(loopEndNumber);

    const loopActive = document.createElement("input");
    loopActive.type = "checkbox";
    loopActive.oninput = loopActiveCallback;
    uiDiv.appendChild(loopActive);

    return uiDiv;
}

export function uiCreateSingstarUi(songDuration, songBars, tracks, trackSelectCallback, startCallback) {
    const uiDiv = document.createElement("div");
    uiDiv.id = "uiDiv";

    const progressSpan = document.createElement("span");
    progressSpan.innerText = usToMinSec(0);
    progressSpan.id = "progressSpan";
    uiDiv.appendChild(progressSpan);

    const durationSpan = document.createElement("span");
    durationSpan.innerText = "".concat(" / ", usToMinSec(songDuration));
    uiDiv.appendChild(durationSpan);

    const progressBar = document.createElement("input");
    progressBar.type = "range";
    progressBar.id = "progressBar";
    progressBar.min = 0;
    progressBar.max = songDuration;
    progressBar.value = 0;
    progressBar.readOnly = true; // Has no effect for range input, unfortunately
    uiDiv.appendChild(progressBar);

    const barLabel = document.createElement("label");
    barLabel.innerText = "Bar";
    uiDiv.appendChild(barLabel);

    const barNumber = document.createElement("input");
    barNumber.type = "number";
    barNumber.id = "barNumber";
    barNumber.min = 0; // 1?
    barNumber.max = songBars;
    barNumber.value = 0;
    barNumber.readOnly = true;
    uiDiv.appendChild(barNumber);

    const trackSelect = document.createElement("select");
    const option = document.createElement("option");
    option.innerText = "Velg et spor";
    option.disabled = true;
    option.selected = true;
    trackSelect.appendChild(option);
    for (const track of tracks) {
        if (track.event.every(e => e.type != MIDI.MESSAGE_TYPE_NOTEON)) {
            continue;
        }
        const option = document.createElement("option");
        option.value = track.trackId;
        option.innerText = track.label;
        trackSelect.appendChild(option);
    }
    trackSelect.oninput = trackSelectCallback;
    uiDiv.appendChild(trackSelect);

    const startButton = document.createElement("button");
    startButton.innerText = "Start";
    startButton.id = "startButton";
    startButton.onclick = startCallback;
    uiDiv.appendChild(startButton);

    const scoreLabel = document.createElement("label");
    scoreLabel.innerText = "Score: ";
    uiDiv.appendChild(scoreLabel);

    const scoreSpan = document.createElement("span");
    scoreSpan.innerText = "N/A";
    scoreSpan.id = "scoreSpan";
    uiDiv.appendChild(scoreSpan);

    const highscoreLabel = document.createElement("label");
    highscoreLabel.innerText = "Highscore: ";
    uiDiv.appendChild(highscoreLabel);

    const highscoreSpan = document.createElement("span");
    highscoreSpan.innerText = "N/A";
    highscoreSpan.id = "highscoreSpan";
    uiDiv.appendChild(highscoreSpan);

    return uiDiv;
}

export function uiSetStartButtonText(text) {
    const startButton = document.getElementById("startButton");
    startButton.innerText = text;
}

export function uiCreateTrackUi(label, volumeCallback, balanceCallback, muteCallback, soloCallback) {
    const trackUiDiv = document.createElement("div");
    trackUiDiv.innerText = label;

    const volumeLabel = document.createElement("label");
    volumeLabel.innerText = "Volume";
    trackUiDiv.appendChild(volumeLabel);

    const volumeSlider = document.createElement("input");
    volumeSlider.type = "range";
    volumeSlider.min = PLAYER.VOLUME.MIN;
    volumeSlider.max = PLAYER.VOLUME.MAX;
    volumeSlider.value = PLAYER.VOLUME.DEFAULT;
    volumeSlider.oninput = volumeCallback;
    trackUiDiv.appendChild(volumeSlider);

    const balanceLabel = document.createElement("label");
    balanceLabel.innerText = "Balance";
    trackUiDiv.appendChild(balanceLabel);

    const balanceSlider = document.createElement("input");
    balanceSlider.type = "range";
    balanceSlider.min = PLAYER.BALANCE.MIN;
    balanceSlider.max = PLAYER.BALANCE.MAX;
    balanceSlider.value = PLAYER.BALANCE.DEFAULT;
    balanceSlider.oninput = balanceCallback;
    trackUiDiv.appendChild(balanceSlider);

    const muteButton = document.createElement("button");
    muteButton.innerText = "Mute";
    muteButton.onclick = muteCallback;
    trackUiDiv.appendChild(muteButton);

    const soloButton = document.createElement("input");
    soloButton.type = "radio";
    soloButton.name = "soloButton";
    soloButton.onclick = soloCallback;
    trackUiDiv.appendChild(soloButton);

    return trackUiDiv;
}

function usToMinSec(us) {
    const secs = us/1000000;
    const mins = Math.trunc(secs/60);
    const overshootingSecs = Math.trunc(secs % 60);
    return "".concat(mins, overshootingSecs < 10 ? ":0" : ":", overshootingSecs);
}

export function uiSetProgress(time, bar) {
    const progressBar = document.getElementById("progressBar");
    progressBar.value = time;
    const progressSpan = document.getElementById("progressSpan");
    progressSpan.innerText = usToMinSec(time);
    const barNumber = document.getElementById("barNumber");
    barNumber.value = Math.floor(bar);
}

export function uiSetScore(score) {
    const scoreSpan = document.getElementById("scoreSpan");
    scoreSpan.innerText = score.toFixed(SCORE.DISPLAY_DECIMALS);
}

export function uiSetHighscore(highscore) {
    const highscoreSpan = document.getElementById("highscoreSpan");
    highscoreSpan.innerText = highscore.toFixed(SCORE.DISPLAY_DECIMALS);
}

export function uiReset() {
    const uiDiv = document.getElementById("uiDiv");
    uiDiv.innerHTML = "";
}
