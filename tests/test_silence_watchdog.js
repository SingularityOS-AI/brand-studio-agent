// PIEZA 18 -> PIEZA 19 (arreglo de deuda): autochequeo de shouldSuspendForSilence
// sin abrir una sesion real, MORDIENDO de verdad.
//
// La version anterior declaraba su PROPIA copia de la funcion en este archivo.
// Se comprobo que eso no muerde: cambiar shouldSuspendForSilence en app.js para
// que siempre devolviera `false` dejaba este test en verde 4/4 igual, porque
// nunca ejercitaba el codigo real.
//
// Arreglo: leer app/static/app.js en disco, extraer el CODIGO FUENTE real de
// shouldSuspendForSilence (contando llaves balanceadas, no una sola linea a
// ciegas) y evaluarlo con vm. Si alguien rompe la funcion en app.js, este
// test usa esa version rota y el assert de abajo falla.
//
// Uso: node tests/test_silence_watchdog.js
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const APP_JS_PATH = path.join(__dirname, '..', 'app', 'static', 'app.js');
const source = fs.readFileSync(APP_JS_PATH, 'utf8');

const MARKER = 'function shouldSuspendForSilence';
const startIdx = source.indexOf(MARKER);
assert.ok(
  startIdx !== -1,
  `no se encontro '${MARKER}' en ${APP_JS_PATH} — la firma cambio o la funcion se movio/renombro`
);

// Extraer el cuerpo completo contando llaves balanceadas: no asumir que el
// cuerpo cabe en una sola linea ni una cantidad fija de ellas.
let braceDepth = 0;
let bodyStarted = false;
let endIdx = -1;
for (let i = startIdx; i < source.length; i++) {
  const ch = source[i];
  if (ch === '{') {
    braceDepth++;
    bodyStarted = true;
  } else if (ch === '}') {
    braceDepth--;
    if (bodyStarted && braceDepth === 0) {
      endIdx = i + 1;
      break;
    }
  }
}
assert.ok(
  endIdx !== -1,
  'no se pudo extraer el cuerpo completo de shouldSuspendForSilence (llaves sin balancear)'
);

const fnSource = source.slice(startIdx, endIdx);

// Evalua el codigo REAL leido de app.js en un sandbox aislado (vm), no una
// copia mantenida a mano en este archivo.
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(`${fnSource}\nthis.shouldSuspendForSilence = shouldSuspendForSilence;`, sandbox);
const { shouldSuspendForSilence } = sandbox;
assert.strictEqual(
  typeof shouldSuspendForSilence,
  'function',
  'la extraccion no produjo una funcion invocable'
);

const THRESHOLD = 45000;
const now = 1000000;

// Por debajo del umbral: no suspende
assert.strictEqual(shouldSuspendForSilence(now - 44999, now, THRESHOLD), false, 'no debe suspender a 44.999s');
assert.strictEqual(shouldSuspendForSilence(now - 1000, now, THRESHOLD), false, 'no debe suspender a 1s');

// Justo en el umbral y por encima: suspende
assert.strictEqual(shouldSuspendForSilence(now - 45000, now, THRESHOLD), true, 'debe suspender exactamente a 45s');
assert.strictEqual(shouldSuspendForSilence(now - 60000, now, THRESHOLD), true, 'debe suspender a 60s');

console.log('OK: shouldSuspendForSilence (extraida de app/static/app.js) — 4/4 asserts pasaron');
