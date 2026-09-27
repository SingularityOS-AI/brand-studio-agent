/**
 * Brand Studio Agent -- Confirmation engine (Block F, F-06)
 *
 * Principle 3 / A-D1 (docs/specs/F/spec.md), semantics from
 * docs/specs/F/plan.md #2 "Confirmation engine": Brandy proposes a paid or
 * destructive action, restates it, and only executes it once the founder's
 * next final voice utterance is an explicit, short confirmation. Anything
 * else -- silence, a correction, "no", a long unrelated sentence -- drops
 * the pending proposal instead of running it.
 *
 * Pure state engine: no DOM, no network, no globals besides `Date.now()` /
 * `Math.random()`. This module only decides whether an utterance confirms,
 * cancels, or drops the current proposal -- wiring it to the real
 * `propose_action` / `confirm_action` tool handlers and to app.js's final
 * transcript event is a later piece's job (see plan.md's F-06 row: "pure JS
 * module + Node tests, then Antigravity wires it").
 *
 * Exported for both Node (`module.exports`) and the browser
 * (`window.createConfirmationEngine` / `window.BrandStudioConfirmEngine`).
 */
(function () {
  'use strict';

  // Word lists from plan.md #2, case/accent-insensitive. Already written in
  // this module's own normalized form (lowercase, no accents, apostrophes
  // treated as word separators) since normalizeText() is applied to both
  // sides of every comparison.
  var CONFIRM_WORDS = [
    'confirm',
    'confirmed',
    'yes do it',
    'go ahead',
    'do it',
    'confirmo',
    'si hazlo',
    'hazlo',
    'dale',
    'adelante',
  ];

  var CANCEL_WORDS = [
    'no',
    "don't",
    'wait',
    'cancel',
    'stop',
    'espera',
    'cancela',
    'para',
  ];

  function normalizeText(input) {
    if (typeof input !== 'string') return '';
    var noAccents = typeof input.normalize === 'function'
      ? input.normalize('NFD').replace(/[̀-ͯ]/g, '')
      : input;
    var cleaned = noAccents.toLowerCase().replace(/[^a-z0-9]+/g, ' ');
    return cleaned.replace(/\s+/g, ' ').trim();
  }

  function containsPhrase(normalizedText, phrase) {
    var normalizedPhrase = normalizeText(phrase);
    if (!normalizedPhrase) return false;
    return (' ' + normalizedText + ' ').indexOf(' ' + normalizedPhrase + ' ') !== -1;
  }

  function wordCount(normalizedText) {
    return normalizedText ? normalizedText.split(' ').filter(Boolean).length : 0;
  }

  function randomToken() {
    return Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
  }

  function snapshot(proposal) {
    return {
      token: proposal.token,
      actionId: proposal.actionId,
      args: proposal.args,
      cost: proposal.cost,
      expiresAt: proposal.expiresAt,
    };
  }

  function createConfirmationEngine(options) {
    // 45s TTL default per docs/specs/F/plan.md #2 ("token (random), 45 s TTL").
    var maxAgeMs = options && typeof options.maxAgeMs === 'number' ? options.maxAgeMs : 45000;
    var proposal = null;

    // propose({actionId, args, cost, expiresAt}) -- stores the one pending
    // proposal, replacing any previous one (one at a time, per plan.md).
    function propose(request) {
      request = request || {};
      var now = Date.now();
      var expiresAt = typeof request.expiresAt === 'number' ? request.expiresAt : now + maxAgeMs;
      proposal = {
        token: randomToken(),
        actionId: request.actionId,
        args: request.args,
        cost: request.cost,
        createdAt: now,
        expiresAt: expiresAt,
      };
      return snapshot(proposal);
    }

    // pending() -- current proposal, or null if none or expired (an expired
    // proposal is cleared as a side effect of checking it).
    function pending() {
      if (!proposal) return null;
      if (Date.now() > proposal.expiresAt) {
        proposal = null;
        return null;
      }
      return snapshot(proposal);
    }

    // cancel() -- drops the pending proposal unconditionally. Returns
    // whether there was one to drop.
    function cancel() {
      var had = pending() !== null;
      proposal = null;
      return had;
    }

    // confirm(userUtterance) -- code-enforced gate: an action is only ever
    // returned when there is a valid (unexpired) proposal AND the utterance
    // is an explicit confirmation. Every call, whatever it decides, drops
    // the pending proposal -- there is no way to accumulate confirmations
    // across turns.
    function confirm(userUtterance) {
      var current = pending();
      if (!current) {
        return { status: 'not_confirmed', reason: 'no_pending_proposal', action: null };
      }

      var normalized = normalizeText(userUtterance);

      var isCancel = CANCEL_WORDS.some(function (word) {
        return containsPhrase(normalized, word);
      });
      if (isCancel) {
        proposal = null;
        return { status: 'cancelled', reason: 'cancel_word', action: null };
      }

      var count = wordCount(normalized);
      var isConfirm = count > 0 && count <= 6 && CONFIRM_WORDS.some(function (word) {
        return containsPhrase(normalized, word);
      });
      if (isConfirm) {
        var action = {
          actionId: current.actionId,
          args: current.args,
          cost: current.cost,
          token: current.token,
        };
        proposal = null;
        return { status: 'confirmed', reason: 'confirm_word', action: action };
      }

      proposal = null;
      return { status: 'not_confirmed', reason: 'no_match', action: null };
    }

    return { propose: propose, confirm: confirm, cancel: cancel, pending: pending };
  }

  var api = { createConfirmationEngine: createConfirmationEngine };

  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  }
  if (typeof window !== 'undefined') {
    window.createConfirmationEngine = createConfirmationEngine;
    window.BrandStudioConfirmEngine = api;
  } else if (typeof self !== 'undefined') {
    self.createConfirmationEngine = createConfirmationEngine;
  }
})();
