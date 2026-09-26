(function () {
  "use strict";

  function layoutText(kind, linesOrText) {
    var K = 0.58;
    if (!linesOrText) {
      var defaultPx = kind === "hero" ? 170 : (kind === "block" ? 84 : 110);
      return { lines: [], fontPx: defaultPx };
    }
    if (kind === "frame_zero") {
      var words = [];
      if (typeof linesOrText === "string") {
        words = linesOrText.trim().split(/\s+/).filter(Boolean);
      } else if (Array.isArray(linesOrText)) {
        for (var i = 0; i < linesOrText.length; i++) {
          var item = linesOrText[i];
          if (typeof item === "string") {
            var parts = item.trim().split(/\s+/).filter(Boolean);
            for (var p = 0; p < parts.length; p++) words.push(parts[p]);
          } else if (item && item.text) {
            words.push(String(item.text));
          }
        }
      }
      var lines = [];
      var currentLine = "";
      for (var w = 0; w < words.length; w++) {
        var word = words[w];
        if (!currentLine) {
          currentLine = word;
        } else if (currentLine.length + 1 + word.length <= 16) {
          currentLine += " " + word;
        } else {
          if (lines.length < 2) {
            lines.push(currentLine);
            currentLine = word;
          } else {
            currentLine += " " + word;
          }
        }
      }
      if (currentLine) {
        lines.push(currentLine);
      }
      var maxLen = 0;
      for (var l = 0; l < lines.length; l++) {
        if (lines[l].length > maxLen) maxLen = lines[l].length;
      }
      var fontPx = maxLen > 0 ? Math.min(110, Math.floor(900 / (K * maxLen))) : 110;
      return { lines: lines, fontPx: fontPx };
    } else if (kind === "hero") {
      var str = "";
      if (typeof linesOrText === "string") {
        str = linesOrText.trim();
      } else if (Array.isArray(linesOrText)) {
        str = linesOrText.map(function (t) {
          return typeof t === "string" ? t : (t && t.text ? t.text : "");
        }).join(" ").trim();
      }
      var wordLen = str.length;
      var heroFontPx = wordLen > 0 ? Math.min(170, Math.floor(900 / (K * wordLen))) : 170;
      return { lines: [str], fontPx: heroFontPx };
    } else {
      var blockLines = [];
      var rawLines = Array.isArray(linesOrText) ? linesOrText : [linesOrText];
      for (var b = 0; b < rawLines.length; b++) {
        var rLine = rawLines[b];
        if (typeof rLine === "string") {
          blockLines.push(rLine);
        } else if (Array.isArray(rLine)) {
          var lineStr = rLine.map(function (t) {
            return typeof t === "string" ? t : (t && t.text ? t.text : "");
          }).join(" ");
          blockLines.push(lineStr);
        }
      }
      var maxBlockLen = 0;
      for (var m = 0; m < blockLines.length; m++) {
        if (blockLines[m].length > maxBlockLen) maxBlockLen = blockLines[m].length;
      }
      var blockFontPx = maxBlockLen > 0 ? Math.min(84, Math.floor(900 / (K * maxBlockLen))) : 84;
      return { lines: blockLines, fontPx: blockFontPx };
    }
  }

  function zoomAt(keys, tMs) {
    if (!keys || !Array.isArray(keys) || keys.length === 0) {
      return { scale: 1.0, cx: 0.5, cy: 0.5 };
    }
    var sorted = keys.slice().sort(function (a, b) {
      return a.t_ms - b.t_ms;
    });
    if (tMs <= sorted[0].t_ms) {
      return {
        scale: Number(sorted[0].scale),
        cx: Number(sorted[0].cx),
        cy: Number(sorted[0].cy)
      };
    }
    if (tMs >= sorted[sorted.length - 1].t_ms) {
      var kn = sorted[sorted.length - 1];
      return {
        scale: Number(kn.scale),
        cx: Number(kn.cx),
        cy: Number(kn.cy)
      };
    }
    for (var i = 0; i < sorted.length - 1; i++) {
      var k1 = sorted[i];
      var k2 = sorted[i + 1];
      if (tMs >= k1.t_ms && tMs <= k2.t_ms) {
        var dt = k2.t_ms - k1.t_ms;
        if (dt <= 0) {
          return {
            scale: Number(k2.scale),
            cx: Number(k2.cx),
            cy: Number(k2.cy)
          };
        }
        var p = (tMs - k1.t_ms) / dt;
        var ease = k2.ease || "linear";
        var e = p;
        if (ease === "out") {
          e = 1.0 - (1.0 - p) * (1.0 - p);
        }
        var s1 = Number(k1.scale);
        var s2 = Number(k2.scale);
        var cx1 = Number(k1.cx);
        var cx2 = Number(k2.cx);
        var cy1 = Number(k1.cy);
        var cy2 = Number(k2.cy);

        var scale = s1 + (s2 - s1) * e;
        var cx = cx1 + (cx2 - cx1) * e;
        var cy = cy1 + (cy2 - cy1) * e;
        return { scale: scale, cx: cx, cy: cy };
      }
    }
    var last = sorted[sorted.length - 1];
    return {
      scale: Number(last.scale),
      cx: Number(last.cx),
      cy: Number(last.cy)
    };
  }

  function stateAt(ir, tMs) {
    var frameZero = null;
    if (ir && ir.frame_zero) {
      var fz = ir.frame_zero;
      if (tMs >= fz.start_ms && tMs < fz.end_ms) {
        frameZero = fz.text;
      }
    }

    var caption = null;
    if (ir && ir.captions && Array.isArray(ir.captions)) {
      var event = null;
      for (var i = 0; i < ir.captions.length; i++) {
        var ev = ir.captions[i];
        if (tMs >= ev.start_ms && tMs < ev.end_ms) {
          event = ev;
          break;
        }
      }
      if (event) {
        var allTokens = [];
        if (event.lines && Array.isArray(event.lines)) {
          for (var l = 0; l < event.lines.length; l++) {
            var line = event.lines[l];
            if (Array.isArray(line)) {
              for (var t = 0; t < line.length; t++) {
                allTokens.push(line[t]);
              }
            }
          }
        }
        var activeTok = null;
        for (var k = 0; k < allTokens.length; k++) {
          var tok = allTokens[k];
          if (tok.start_ms <= tMs) {
            if (!activeTok || tok.start_ms > activeTok.start_ms) {
              activeTok = tok;
            }
          }
        }
        if (!activeTok && allTokens.length > 0) {
          activeTok = allTokens[0];
        }

        var formattedLines = [];
        if (event.lines && Array.isArray(event.lines)) {
          for (var l2 = 0; l2 < event.lines.length; l2++) {
            var line2 = event.lines[l2];
            var lineItems = [];
            if (Array.isArray(line2)) {
              for (var t2 = 0; t2 < line2.length; t2++) {
                var tok2 = line2[t2];
                lineItems.push({
                  text: tok2.text,
                  active: tok2 === activeTok
                });
              }
            }
            formattedLines.push(lineItems);
          }
        }

        caption = {
          size: event.size,
          lines: formattedLines
        };
      }
    }

    var zoom = zoomAt(ir ? ir.zoom_keys : [], tMs);

    var flash = 0;
    var blurPx = 0;
    var blurAxis = null;

    if (ir && ir.transitions && Array.isArray(ir.transitions)) {
      for (var trIdx = 0; trIdx < ir.transitions.length; trIdx++) {
        var tr = ir.transitions[trIdx];
        var at = tr.at_ms;
        var dur = tr.dur_ms || 0;
        if (tr.type === "flash") {
          if (tMs >= at && tMs < at + dur) {
            var val = 0.8 * (1 - (tMs - at) / dur);
            if (val > flash) flash = val;
          }
        } else if (tr.type === "zoom_through") {
          if (tMs >= at && tMs < at + dur / 2) {
            blurPx = 12;
            blurAxis = "both";
          }
        } else if (tr.type === "whip") {
          if (tMs >= at - dur / 2 && tMs < at + dur / 2) {
            blurPx = 20;
            blurAxis = "x";
          }
        }
      }
    }

    var overlays = [];
    if (ir && ir.overlays && Array.isArray(ir.overlays)) {
      for (var ovIdx = 0; ovIdx < ir.overlays.length; ovIdx++) {
        var ov = ir.overlays[ovIdx];
        if (tMs >= ov.start_ms && tMs < ov.end_ms) {
          var start = ov.start_ms;
          var end = ov.end_ms;
          var inFade = (tMs - start) / 200;
          var outFade = (end - tMs) / 150;
          var opacity = Math.min(1, Math.min(inFade, outFade));
          if (opacity < 0) opacity = 0;
          if (opacity > 1) opacity = 1;

          overlays.push({
            id: ov.id,
            kind: ov.kind,
            text: ov.text !== undefined ? ov.text : null,
            asset: ov.asset !== undefined ? ov.asset : null,
            x: ov.x,
            y: ov.y,
            w: ov.w,
            h: ov.h,
            accent: Boolean(ov.accent),
            opacity: opacity
          });
        }
      }
    }

    return {
      frameZero: frameZero,
      caption: caption,
      zoom: zoom,
      flash: flash,
      blurPx: blurPx,
      blurAxis: blurAxis,
      overlays: overlays
    };
  }

  function mount(container, videoEl, ir, opts) {
    var currentIr = ir || null;
    var sfxMap = {};
    var audioCache = {};
    var isDestroyed = false;
    var animFrameId = null;
    var rvfcId = null;
    var lastTimeMs = null;

    var layer = document.createElement("div");
    layer.style.position = "absolute";
    layer.style.inset = "0";
    layer.style.pointerEvents = "none";
    layer.style.overflow = "hidden";

    var stage = document.createElement("div");
    stage.style.position = "absolute";
    stage.style.left = "0";
    stage.style.top = "0";
    stage.style.width = "1080px";
    stage.style.height = "1920px";
    stage.style.transformOrigin = "0 0";
    stage.style.pointerEvents = "none";
    layer.appendChild(stage);

    var flashEl = document.createElement("div");
    flashEl.style.position = "absolute";
    flashEl.style.inset = "0";
    flashEl.style.backgroundColor = "#ffffff";
    flashEl.style.opacity = "0";
    flashEl.style.pointerEvents = "none";
    stage.appendChild(flashEl);

    var fzEl = document.createElement("div");
    fzEl.style.position = "absolute";
    fzEl.style.top = "50%";
    fzEl.style.left = "90px";
    fzEl.style.right = "90px";
    fzEl.style.transform = "translateY(-50%)";
    fzEl.style.textAlign = "center";
    fzEl.style.fontSize = "110px";
    fzEl.style.fontWeight = "bold";
    fzEl.style.backgroundColor = "rgba(0, 0, 0, 0.6)";
    fzEl.style.padding = "20px 40px";
    fzEl.style.borderRadius = "16px";
    fzEl.style.boxSizing = "border-box";
    fzEl.style.display = "none";
    stage.appendChild(fzEl);

    var overlayLayer = document.createElement("div");
    overlayLayer.style.position = "absolute";
    overlayLayer.style.inset = "0";
    overlayLayer.style.pointerEvents = "none";
    stage.appendChild(overlayLayer);

    var subBox = document.createElement("div");
    subBox.style.position = "absolute";
    subBox.style.left = "90px";
    subBox.style.right = "90px";
    subBox.style.pointerEvents = "none";
    subBox.style.textAlign = "center";
    subBox.style.display = "none";
    stage.appendChild(subBox);

    var overlayNodes = {};

    function isHttpsUrl(u) {
      if (!u || typeof u !== "string") return false;
      try {
        var parsed = new URL(u);
        return parsed.protocol === "https:";
      } catch (e) {
        return false;
      }
    }

    function createOverlayNode(stOv, fontFamily, accentColor) {
      var el = document.createElement("div");
      el.style.position = "absolute";
      el.style.left = stOv.x + "px";
      el.style.top = stOv.y + "px";
      el.style.width = stOv.w + "px";
      el.style.height = stOv.h + "px";
      el.style.boxSizing = "border-box";
      el.style.pointerEvents = "none";
      el._valid = true;

      if (stOv.kind === "broll_card") {
        var img = document.createElement("img");
        img.style.width = "100%";
        img.style.height = "100%";
        img.style.objectFit = "cover";
        img.style.borderRadius = "28px";
        img.style.border = "6px solid #ffffff";
        img.style.boxSizing = "border-box";
        img.style.display = "block";

        var url = sfxMap ? sfxMap[stOv.asset] : null;
        if (isHttpsUrl(url)) {
          img.src = url;
          el._valid = true;
        } else {
          el._valid = false;
        }
        el.appendChild(img);
      } else if (stOv.kind === "emoji") {
        el.style.display = "flex";
        el.style.alignItems = "center";
        el.style.justifyContent = "center";
        el.style.fontSize = "180px";
        el.style.lineHeight = "1";
        el.textContent = stOv.asset || stOv.text || "";
      } else {
        el.style.backgroundColor = "rgba(10, 12, 20, 0.82)";
        el.style.borderRadius = "28px";
        var borderColor = stOv.accent ? accentColor : "rgba(255, 255, 255, 0.2)";
        el.style.border = "3px solid " + borderColor;
        el.style.color = "#ffffff";
        el.style.fontWeight = "bold";
        el.style.fontFamily = fontFamily;
        el.style.display = "flex";
        el.style.alignItems = "center";
        el.style.padding = "20px 30px";
        el.style.overflow = "hidden";
        el.style.wordBreak = "break-word";

        var fontSizes = {
          card_stat: "110px",
          card_quote: "60px",
          card_list: "50px",
          card_lower_third: "44px",
          onscreen_text: "64px"
        };
        el.style.fontSize = fontSizes[stOv.kind] || "64px";

        if (stOv.kind === "card_quote") {
          el.style.fontStyle = "italic";
        }

        if (stOv.kind === "card_lower_third") {
          el.style.justifyContent = "flex-start";
          el.style.textAlign = "left";
        } else {
          el.style.justifyContent = "center";
          el.style.textAlign = "center";
        }

        var textContent = stOv.text || "";
        if (stOv.kind === "card_quote" && textContent) {
          if (!textContent.startsWith('"') && !textContent.startsWith("“")) {
            textContent = "“" + textContent + "”";
          }
        }
        el.textContent = textContent;
      }

      return el;
    }

    function updateOverlayNode(el, stOv, fontFamily, accentColor) {
      el.style.left = stOv.x + "px";
      el.style.top = stOv.y + "px";
      el.style.width = stOv.w + "px";
      el.style.height = stOv.h + "px";

      if (stOv.kind === "broll_card") {
        var url = sfxMap ? sfxMap[stOv.asset] : null;
        var img = el.querySelector("img");
        if (isHttpsUrl(url)) {
          if (img && img.src !== url) {
            img.src = url;
          }
          el._valid = true;
        } else {
          el._valid = false;
        }
      } else if (stOv.kind === "emoji") {
        el.textContent = stOv.asset || stOv.text || "";
      } else {
        var borderColor = stOv.accent ? accentColor : "rgba(255, 255, 255, 0.2)";
        el.style.border = "3px solid " + borderColor;
        el.style.fontFamily = fontFamily;
        var textContent = stOv.text || "";
        if (stOv.kind === "card_quote" && textContent) {
          if (!textContent.startsWith('"') && !textContent.startsWith("“")) {
            textContent = "“" + textContent + "”";
          }
        }
        el.textContent = textContent;
      }
    }

    if (container) {
      if (getComputedStyle(container).position === "static") {
        container.style.position = "relative";
      }
      container.appendChild(layer);
    }

    function getScale() {
      if (!container || !container.clientWidth) return 1.0;
      return container.clientWidth / 1080;
    }

    function setSfxUrls(map) {
      if (!map) return;
      sfxMap = map;
      for (var id in map) {
        if (Object.prototype.hasOwnProperty.call(map, id) && map[id]) {
          try {
            var a = new Audio(map[id]);
            a.preload = "auto";
            audioCache[id] = a;
          } catch (e) {}
        }
      }
      onSeekOrPause();
    }

    function playSfx(inputId, gainDb) {
      var src = audioCache[inputId];
      if (src) {
        try {
          var clone = src.cloneNode(true);
          var gain = Math.pow(10, gainDb / 20);
          clone.volume = Math.min(1, Math.max(0, gain));
          clone.play().catch(function () {});
        } catch (e) {}
      }
    }

    function applyState(st) {
      if (!st) return;

      var fontName = currentIr && currentIr.style && currentIr.style.font ? currentIr.style.font : "Inter";
      var textColor = currentIr && currentIr.style && currentIr.style.text ? currentIr.style.text : "#FFFFFF";
      var accentColor = currentIr && currentIr.style && currentIr.style.accent ? currentIr.style.accent : "#FFFF00";
      var outlineColor = currentIr && currentIr.style && currentIr.style.outline ? currentIr.style.outline : "#000000";
      var fontFamily = '"' + fontName + '", sans-serif';

      // 1. FrameZero
      if (st.frameZero) {
        var fzLayout = layoutText("frame_zero", st.frameZero);
        fzEl.textContent = fzLayout.lines.join("\n");
        fzEl.style.whiteSpace = "pre-wrap";
        fzEl.style.fontFamily = fontFamily;
        fzEl.style.color = textColor;
        fzEl.style.fontSize = fzLayout.fontPx + "px";
        fzEl.style.webkitTextStroke = "7px " + outlineColor;
        fzEl.style.paintOrder = "stroke fill";
        fzEl.style.backgroundColor = "rgba(0, 0, 0, 0.6)";
        fzEl.style.display = "block";
      } else {
        fzEl.style.display = "none";
      }

      // 2. Subtitles
      if (st.caption) {
        subBox.style.display = "block";
        subBox.style.fontFamily = fontFamily;

        while (subBox.firstChild) {
          subBox.removeChild(subBox.firstChild);
        }

        if (st.caption.size === "hero") {
          subBox.style.top = "50%";
          subBox.style.bottom = "auto";
          subBox.style.transform = "translateY(-50%)";
          var heroText = "";
          for (var h1 = 0; h1 < st.caption.lines.length; h1++) {
            for (var h2 = 0; h2 < st.caption.lines[h1].length; h2++) {
              if (st.caption.lines[h1][h2].active) {
                heroText = st.caption.lines[h1][h2].text;
              }
            }
          }
          if (!heroText && st.caption.lines[0] && st.caption.lines[0][0]) {
            heroText = st.caption.lines[0][0].text;
          }
          var heroLayout = layoutText("hero", heroText);
          subBox.style.fontSize = heroLayout.fontPx + "px";
          subBox.style.fontWeight = "bold";
          subBox.style.lineHeight = "1.1";
          subBox.style.webkitTextStroke = "8px " + outlineColor;
          subBox.style.paintOrder = "stroke fill";
          subBox.style.textShadow = "none";
        } else {
          subBox.style.top = "1250px";
          subBox.style.bottom = "auto";
          subBox.style.transform = "translateY(-100%)";
          var blockLayout = layoutText("block", st.caption.lines);
          subBox.style.fontSize = blockLayout.fontPx + "px";
          subBox.style.fontWeight = "bold";
          subBox.style.lineHeight = "1.15";
          subBox.style.webkitTextStroke = "6px " + outlineColor;
          subBox.style.paintOrder = "stroke fill";
          subBox.style.textShadow = "2px 2px 4px rgba(0,0,0,0.8)";
        }

        for (var i = 0; i < st.caption.lines.length; i++) {
          var lineDiv = document.createElement("div");
          var tokens = st.caption.lines[i];
          for (var j = 0; j < tokens.length; j++) {
            var tok = tokens[j];
            var span = document.createElement("span");
            span.textContent = tok.text + (j < tokens.length - 1 ? " " : "");
            span.style.color = tok.active ? accentColor : textColor;
            lineDiv.appendChild(span);
          }
          subBox.appendChild(lineDiv);
        }
      } else {
        subBox.style.display = "none";
      }

      // 3. Zoom on videoEl
      if (videoEl && st.zoom) {
        videoEl.style.transformOrigin = (st.zoom.cx * 100) + "% " + (st.zoom.cy * 100) + "%";
        var baseTransform = "scale(" + st.zoom.scale + ")";
        if (st.blurPx > 0 && st.blurAxis === "x") {
          baseTransform += " scaleX(1.05)";
        }
        videoEl.style.transform = baseTransform;
      }

      // 4. Flash
      flashEl.style.opacity = String(st.flash);

      // 5. Blur on videoEl
      if (videoEl) {
        var s = getScale();
        if (st.blurPx > 0) {
          var scaledBlur = Math.round(st.blurPx * s * 10) / 10;
          videoEl.style.filter = "blur(" + scaledBlur + "px)";
        } else {
          videoEl.style.filter = "";
        }
      }

      // 6. Overlays
      var activeIds = {};
      if (st.overlays && Array.isArray(st.overlays)) {
        for (var oIdx = 0; oIdx < st.overlays.length; oIdx++) {
          var stOv = st.overlays[oIdx];
          activeIds[stOv.id] = true;
          var node = overlayNodes[stOv.id];

          if (!node) {
            node = createOverlayNode(stOv, fontFamily, accentColor);
            overlayNodes[stOv.id] = node;
            overlayLayer.appendChild(node);
          } else {
            updateOverlayNode(node, stOv, fontFamily, accentColor);
          }

          var targetDisplay = stOv.kind === "broll_card" ? "block" : "flex";
          node.style.display = node._valid === false ? "none" : targetDisplay;
          node.style.opacity = String(stOv.opacity);
        }
      }

      for (var existingId in overlayNodes) {
        if (!activeIds[existingId]) {
          overlayNodes[existingId].style.display = "none";
          overlayNodes[existingId].style.opacity = "0";
        }
      }
    }

    function renderFrame() {
      if (isDestroyed) return;
      var s = getScale();
      stage.style.transform = "scale(" + s + ")";

      if (videoEl) {
        var curTimeMs = videoEl.currentTime * 1000;

        if (!videoEl.paused && lastTimeMs !== null && curTimeMs > lastTimeMs && (curTimeMs - lastTimeMs) < 1000) {
          if (currentIr && currentIr.sfx && Array.isArray(currentIr.sfx)) {
            for (var i = 0; i < currentIr.sfx.length; i++) {
              var cue = currentIr.sfx[i];
              if (cue.at_ms > lastTimeMs && cue.at_ms <= curTimeMs) {
                playSfx(cue.input_id, cue.gain_db);
              }
            }
          }
        }
        lastTimeMs = curTimeMs;

        var st = stateAt(currentIr, curTimeMs);
        applyState(st);
      }

      if (videoEl && typeof videoEl.requestVideoFrameCallback === "function") {
        rvfcId = videoEl.requestVideoFrameCallback(renderFrame);
      } else if (typeof requestAnimationFrame === "function") {
        animFrameId = requestAnimationFrame(renderFrame);
      }
    }

    function onSeekOrPause() {
      if (isDestroyed || !videoEl) return;
      lastTimeMs = videoEl.currentTime * 1000;
      var s = getScale();
      stage.style.transform = "scale(" + s + ")";
      var st = stateAt(currentIr, videoEl.currentTime * 1000);
      applyState(st);
    }

    if (videoEl) {
      videoEl.addEventListener("seeking", onSeekOrPause);
      videoEl.addEventListener("seeked", onSeekOrPause);
      videoEl.addEventListener("pause", onSeekOrPause);
      videoEl.addEventListener("timeupdate", onSeekOrPause);
    }

    renderFrame();

    return {
      update: function (newIr) {
        currentIr = newIr || null;
        onSeekOrPause();
      },
      setSfxUrls: setSfxUrls,
      destroy: function () {
        isDestroyed = true;
        if (videoEl) {
          videoEl.removeEventListener("seeking", onSeekOrPause);
          videoEl.removeEventListener("seeked", onSeekOrPause);
          videoEl.removeEventListener("pause", onSeekOrPause);
          videoEl.removeEventListener("timeupdate", onSeekOrPause);
          if (rvfcId && typeof videoEl.cancelVideoFrameCallback === "function") {
            videoEl.cancelVideoFrameCallback(rvfcId);
          }
          videoEl.style.transform = "";
          videoEl.style.transformOrigin = "";
          videoEl.style.filter = "";
        }
        if (animFrameId && typeof cancelAnimationFrame === "function") {
          cancelAnimationFrame(animFrameId);
        }
        if (layer && layer.parentNode) {
          layer.parentNode.removeChild(layer);
        }
      }
    };
  }

  var API = { mount: mount, stateAt: stateAt, zoomAt: zoomAt, layoutText: layoutText };

  if (typeof window !== "undefined") {
    window.BrandStudioPreview = API;
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { stateAt: stateAt, zoomAt: zoomAt, layoutText: layoutText };
  }
})();
