// PIEZA 18 - autochequeo de shouldSuspendForSilence sin abrir una sesion real.
// Uso: node tests/test_silence_watchdog.js
'use strict';
const assert = require('assert');

// Copia deliberada de la funcion pura definida en app/static/app.js (no hay
// modulo exportable ahi: el IIFE no expone nada al exterior). Si cambia la
// firma en app.js, actualizar aqui tambien.
function shouldSuspendForSilence(lastActivityMs, nowMs, thresholdMs) {
  return (nowMs - lastActivityMs) >= thresholdMs;
}

const THRESHOLD = 45000;
const now = 1000000;

// Por debajo del umbral: no suspende
assert.strictEqual(shouldSuspendForSilence(now - 44999, now, THRESHOLD), false, 'no debe suspender a 44.999s');
assert.strictEqual(shouldSuspendForSilence(now - 1000, now, THRESHOLD), false, 'no debe suspender a 1s');

// Justo en el umbral y por encima: suspende
assert.strictEqual(shouldSuspendForSilence(now - 45000, now, THRESHOLD), true, 'debe suspender exactamente a 45s');
assert.strictEqual(shouldSuspendForSilence(now - 60000, now, THRESHOLD), true, 'debe suspender a 60s');

console.log('OK: shouldSuspendForSilence — 4/4 asserts pasaron');
