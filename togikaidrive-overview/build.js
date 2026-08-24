const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");

// ---------------------------------------------------------------------------
// Palette (racing / sensor theme)
// ---------------------------------------------------------------------------
const NAVY = "10131A"; // dominant dark
const STEEL = "1F2A44"; // secondary dark
const STEEL_SOFT = "3A4A6B"; // steel on dark backgrounds (borders, secondary text)
const CYAN = "00B4C6"; // supporting tone (perception)
const ORANGE = "FF4B2B"; // sharp accent
const WHITE = "FFFFFF";
const CARD_BG = "F3F5FA"; // light steel tint for cards on white slides
const TEXT_DARK = "16192A";
const MUTED = "6B7280";
const ORANGE_TINT = "FFEDE9";
const CYAN_TINT = "E4FAFC";
const STEEL_TINT = "EAEEF6";

const FONT_HEAD = "Cambria";
const FONT_BODY = "Calibri";

// ---------------------------------------------------------------------------
// Icon rendering: react-icons -> SVG -> PNG (base64) via sharp
// ---------------------------------------------------------------------------
async function iconDataUri(IconComp, colorHex, px = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(
    React.createElement(IconComp, { size: px })
  ).replace(/currentColor/g, `#${colorHex}`);
  const buf = await sharp(Buffer.from(svg)).resize(px, px).png().toBuffer();
  return "image/png;base64," + buf.toString("base64");
}

async function buildIconSet() {
  const specs = {
    car: [fa.FaCarSide, WHITE],
    car_orange: [fa.FaCarSide, ORANGE],
    eye: [fa.FaEye, WHITE],
    eye_navy: [fa.FaEye, NAVY],
    brain: [fa.FaBrain, WHITE],
    brain_navy: [fa.FaBrain, NAVY],
    cogs: [fa.FaCogs, WHITE],
    cogs_navy: [fa.FaCogs, NAVY],
    sliders_navy: [fa.FaSlidersH, NAVY],
    database_navy: [fa.FaDatabase, NAVY],
    satellite_navy: [fa.FaSatelliteDish, NAVY],
    camera_navy: [fa.FaCamera, NAVY],
    wave_navy: [fa.FaWaveSquare, NAVY],
    gamepad_navy: [fa.FaGamepad, NAVY],
    rocket_white: [fa.FaRocket, WHITE],
    chart_white: [fa.FaChartBar, WHITE],
    broom_white: [fa.FaBroom, WHITE],
    micro_white: [fa.FaMicrochip, WHITE],
    micro_navy: [fa.FaMicrochip, NAVY],
    check_orange: [fa.FaCheckCircle, ORANGE],
    graduation_white: [fa.FaGraduationCap, WHITE],
    bolt_white: [fa.FaBolt, WHITE],
    bolt_navy: [fa.FaBolt, NAVY],
    filter_white: [fa.FaFilter, WHITE],
    map_navy: [fa.FaMapMarkerAlt, NAVY],
    map_white: [fa.FaMapMarkerAlt, WHITE],
    route_navy: [fa.FaRoute, NAVY],
    route_white: [fa.FaRoute, WHITE],
    crosshairs_navy: [fa.FaCrosshairs, NAVY],
    crosshairs_white: [fa.FaCrosshairs, WHITE],
    shield_navy: [fa.FaShieldAlt, NAVY],
    shield_white: [fa.FaShieldAlt, WHITE],
    flask_navy: [fa.FaFlask, NAVY],
    flask_white: [fa.FaFlask, WHITE],
    layers_white: [fa.FaLayerGroup, WHITE],
  };
  const out = {};
  for (const [key, [comp, color]] of Object.entries(specs)) {
    out[key] = await iconDataUri(comp, color, 256);
  }
  return out;
}

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------
function eyebrow(slide, text, opts = {}) {
  slide.addText(text.toUpperCase(), {
    x: opts.x ?? 0.6,
    y: opts.y ?? 0.35,
    w: opts.w ?? 8,
    h: 0.35,
    fontFace: FONT_BODY,
    fontSize: 12,
    bold: true,
    color: opts.color ?? ORANGE,
    charSpacing: 2,
    margin: 0,
  });
}

function slideTitle(slide, text, opts = {}) {
  slide.addText(text, {
    x: opts.x ?? 0.6,
    y: opts.y ?? 0.65,
    w: opts.w ?? 11.5,
    h: opts.h ?? 0.7,
    fontFace: FONT_HEAD,
    fontSize: opts.size ?? 30,
    bold: true,
    color: opts.color ?? TEXT_DARK,
    margin: 0,
  });
}

function pageNum(slide, n, color = MUTED) {
  slide.addText(String(n).padStart(2, "0"), {
    x: 12.6,
    y: 7.05,
    w: 0.6,
    h: 0.3,
    fontFace: FONT_BODY,
    fontSize: 10,
    color,
    align: "right",
    margin: 0,
  });
}

function iconCircle(slide, iconData, cx, cy, dCircle, circleColor, iconScale = 0.52) {
  slide.addShape("ellipse", {
    x: cx - dCircle / 2,
    y: cy - dCircle / 2,
    w: dCircle,
    h: dCircle,
    fill: { color: circleColor },
    line: { type: "none" },
  });
  const dIcon = dCircle * iconScale;
  slide.addImage({
    data: iconData,
    x: cx - dIcon / 2,
    y: cy - dIcon / 2,
    w: dIcon,
    h: dIcon,
  });
}

// Straight connector between two arbitrary points (used for diagonal flow lines).
// Direction of the two endpoints doesn't matter for placement -- pass an explicit
// arrow glyph (see arrowGlyph) at whichever endpoint should show the arrowhead.
function diagLine(slide, x1, y1, x2, y2, opts = {}) {
  const x = Math.min(x1, x2);
  const y = Math.min(y1, y2);
  const w = Math.abs(x2 - x1);
  const h = Math.abs(y2 - y1);
  const startIsLeft = x1 <= x2;
  const startIsTop = y1 <= y2;
  const flipH = startIsLeft !== startIsTop;
  slide.addShape("line", {
    x, y, w, h, flipH,
    line: { color: opts.color || MUTED, width: opts.width || 1.5, dashType: opts.dash || "solid" },
  });
}

function arrowGlyph(slide, cx, cy, glyph, color, size = 13) {
  slide.addText(glyph, {
    x: cx - 0.15, y: cy - 0.13, w: 0.3, h: 0.26,
    align: "center", valign: "middle",
    fontFace: FONT_BODY, fontSize: size, color, margin: 0,
  });
}

async function main() {
  const icon = await buildIconSet();

  const pres = new pptxgen();
  pres.defineLayout({ name: "WIDE", width: 13.333, height: 7.5 });
  pres.layout = "WIDE";

  // =========================================================================
  // Slide 1 — Title
  // =========================================================================
  {
    const s = pres.addSlide();
    s.background = { color: NAVY };

    // subtle geometric motif: concentric arcs suggesting radar/lidar sweep
    s.addShape("ellipse", { x: 9.6, y: -2.6, w: 8, h: 8, fill: { type: "none" }, line: { color: STEEL_SOFT, width: 1.2 } });
    s.addShape("ellipse", { x: 10.4, y: -1.8, w: 6.4, h: 6.4, fill: { type: "none" }, line: { color: STEEL_SOFT, width: 1.2 } });
    s.addShape("ellipse", { x: 11.2, y: -1.0, w: 4.8, h: 4.8, fill: { type: "none" }, line: { color: ORANGE, width: 1.5 } });

    eyebrow(s, "Autonomous Minicar Battle 公式ベースプログラム", { color: CYAN, y: 2.55 });
    s.addText("togikaidrive-dev とは", {
      x: 0.6, y: 2.95, w: 9.6, h: 1.3,
      fontFace: FONT_HEAD, fontSize: 44, bold: true, color: WHITE, margin: 0,
    });
    s.addText("超音波センサ・LiDAR・カメラで自動運転するミニカーのベースプログラム解説", {
      x: 0.6, y: 4.15, w: 8.6, h: 0.6,
      fontFace: FONT_BODY, fontSize: 16, color: "C7CEDE", margin: 0,
    });

    iconCircle(s, icon.car, 11.0, 5.55, 2.0, STEEL);

    s.addText("プログラムが分からない方のための入門資料", {
      x: 0.6, y: 6.7, w: 8, h: 0.4,
      fontFace: FONT_BODY, fontSize: 12, color: STEEL_SOFT, margin: 0,
    });
  }

  // =========================================================================
  // Slide 2 — 全体像（1枚で分かる）
  // =========================================================================
  {
    const s = pres.addSlide();
    s.background = { color: WHITE };
    eyebrow(s, "Overview ― 1枚で分かる全体像");
    slideTitle(s, "全体の流れは、たった3ステップ");

    const steps = [
      { label: "認知", en: "SENSE", desc: "超音波・LiDAR・カメラで\n周囲の状況を測る", ic: icon.eye, color: CYAN },
      { label: "判断", en: "THINK", desc: "得られた情報から\n進む方向と速さを決める", ic: icon.brain, color: ORANGE },
      { label: "操作", en: "ACT", desc: "決めた指示を\nモーターとサーボに伝える", ic: icon.cogs, color: NAVY },
    ];

    const cardW = 3.35, gap = 0.55, startX = 0.75, cy = 3.55, cardTop = 2.15, cardH = 3.0;
    steps.forEach((st, i) => {
      const x = startX + i * (cardW + gap);
      s.addShape("roundRect", {
        x, y: cardTop, w: cardW, h: cardH, rectRadius: 0.12,
        fill: { color: CARD_BG }, line: { type: "none" },
        shadow: { type: "outer", color: "9AA5B8", opacity: 0.35, blur: 8, offset: 3, angle: 90 },
      });
      iconCircle(s, st.ic, x + cardW / 2, cardTop + 0.85, 1.15, st.color);
      s.addText(`0${i + 1}  ${st.label}`, {
        x: x + 0.2, y: cardTop + 1.55, w: cardW - 0.4, h: 0.45,
        fontFace: FONT_HEAD, fontSize: 20, bold: true, color: TEXT_DARK, align: "center", margin: 0,
      });
      s.addText(st.en, {
        x: x + 0.2, y: cardTop + 1.98, w: cardW - 0.4, h: 0.25,
        fontFace: FONT_BODY, fontSize: 10, bold: true, color: st.color === NAVY ? STEEL_SOFT : st.color, align: "center", charSpacing: 2, margin: 0,
      });
      s.addText(st.desc, {
        x: x + 0.25, y: cardTop + 2.3, w: cardW - 0.5, h: 0.65,
        fontFace: FONT_BODY, fontSize: 12.5, color: MUTED, align: "center", margin: 0, lineSpacingMultiple: 1.15,
      });
      if (i < steps.length - 1) {
        s.addText("→", {
          x: x + cardW + 0.05, y: cardTop + cardH / 2 - 0.35, w: gap - 0.1, h: 0.7,
          fontFace: FONT_BODY, fontSize: 26, bold: true, color: MUTED, align: "center", valign: "middle", margin: 0,
        });
      }
    });

    // loop-back note
    s.addShape("roundRect", {
      x: 0.75, y: 5.55, w: startX + 3 * cardW + 2 * gap - 0.75, h: 0.75, rectRadius: 0.1,
      fill: { color: NAVY }, line: { type: "none" },
    });
    s.addText([
      { text: "この3ステップを ", options: { color: "C7CEDE" } },
      { text: "1秒間に何度も", options: { color: ORANGE, bold: true } },
      { text: " 繰り返すことで、ミニカーは自動で走り続ける（run.py のメインループ）", options: { color: "C7CEDE" } },
    ], {
      x: 1.0, y: 5.55, w: 10.7, h: 0.75, valign: "middle",
      fontFace: FONT_BODY, fontSize: 13, margin: 0,
    });

    pageNum(s, 2);
  }

  // =========================================================================
  // Slide 3 — プログラム構成マップ
  // =========================================================================
  {
    const s = pres.addSlide();
    s.background = { color: WHITE };
    eyebrow(s, "Program Map ― どんなプログラムで出来ている？");
    slideTitle(s, "主なプログラムとその役割");

    // run.py — conductor, centered top
    const conductorW = 3.4, conductorH = 0.95;
    const conductorX = 13.333 / 2 - conductorW / 2;
    const conductorY = 1.95;
    s.addShape("roundRect", {
      x: conductorX, y: conductorY, w: conductorW, h: conductorH, rectRadius: 0.14,
      fill: { color: NAVY }, line: { type: "none" },
      shadow: { type: "outer", color: "9AA5B8", opacity: 0.35, blur: 8, offset: 3, angle: 90 },
    });
    iconCircle(s, icon.micro_white, conductorX + 0.62, conductorY + conductorH / 2, 0.62, STEEL);
    s.addText([
      { text: "run.py", options: { bold: true, color: WHITE, fontSize: 16, breakLine: true } },
      { text: "全体をまとめる指揮者", options: { color: "AAB3C6", fontSize: 10.5 } },
    ], {
      x: conductorX + 1.05, y: conductorY, w: conductorW - 1.15, h: conductorH, valign: "middle",
      fontFace: FONT_BODY, margin: 0, lineSpacingMultiple: 1.05,
    });

    // connecting line down
    s.addShape("line", {
      x: 13.333 / 2, y: conductorY + conductorH, w: 0, h: 0.35,
      line: { color: "C6CCDA", width: 1.5 },
    });

    const cards = [
      { name: "config.py", role: "設定 ― 走行モードや速度を決める", ic: icon.sliders_navy, color: STEEL_TINT, accent: STEEL },
      { name: "ultrasonic.py\ncamera.py / lidar.py", role: "認知 ― センサーで周りを見る", ic: icon.eye_navy, color: CYAN_TINT, accent: CYAN },
      { name: "planner.py", role: "判断 ― 走り方のロジックを決める", ic: icon.brain_navy, color: ORANGE_TINT, accent: ORANGE },
      { name: "motor.py", role: "操作 ― ステアリング・モーターへ出力", ic: icon.cogs_navy, color: STEEL_TINT, accent: STEEL },
      { name: "train_pytorch.py", role: "学習 ― 走行データからAIモデルを作る", ic: icon.database_navy, color: CYAN_TINT, accent: CYAN },
      { name: "data_viewer\n(外部Webアプリ)", role: "ツール ― データの可視化・確認", ic: icon.chart_white, color: ORANGE_TINT, accent: ORANGE },
    ];

    const cols = 3, rows = 2;
    const gridTop = 3.55, cardW = 3.75, cardH = 1.62, gx = 0.35, gy = 0.3;
    const gridLeft = (13.333 - (cols * cardW + (cols - 1) * gx)) / 2;
    cards.forEach((c, i) => {
      const col = i % cols, row = Math.floor(i / cols);
      const x = gridLeft + col * (cardW + gx);
      const y = gridTop + row * (cardH + gy);
      s.addShape("roundRect", {
        x, y, w: cardW, h: cardH, rectRadius: 0.1,
        fill: { color: CARD_BG }, line: { type: "none" },
      });
      iconCircle(s, c.ic, x + 0.62, y + cardH / 2, 0.72, c.color);
      s.addText(c.name, {
        x: x + 1.1, y: y + 0.18, w: cardW - 1.3, h: 0.6,
        fontFace: FONT_HEAD, fontSize: 13.5, bold: true, color: TEXT_DARK, margin: 0, lineSpacingMultiple: 1.0,
      });
      s.addText(c.role, {
        x: x + 1.1, y: y + 0.82, w: cardW - 1.3, h: 0.65,
        fontFace: FONT_BODY, fontSize: 10.5, color: MUTED, margin: 0, lineSpacingMultiple: 1.1,
      });
    });

    pageNum(s, 3);
  }

  // =========================================================================
  // Slide 4 — 実行フロー（プログラム間の連携）
  // =========================================================================
  {
    const s = pres.addSlide();
    s.background = { color: WHITE };
    eyebrow(s, "Execution Flow ― プログラムはこの順番で動く");
    slideTitle(s, "実行フロー ― 複数プログラムの連携");

    // ---- Startup row ----
    s.addShape("roundRect", { x: 0.6, y: 1.55, w: 2.7, h: 0.5, rectRadius: 0.08, fill: { color: NAVY }, line: { type: "none" } });
    s.addText("run.py 起動", { x: 0.6, y: 1.55, w: 2.7, h: 0.5, align: "center", valign: "middle", fontFace: FONT_BODY, fontSize: 12.5, bold: true, color: WHITE, margin: 0 });
    s.addText("→", { x: 3.35, y: 1.55, w: 0.4, h: 0.5, align: "center", valign: "middle", fontFace: FONT_BODY, fontSize: 16, bold: true, color: MUTED, margin: 0 });
    s.addShape("roundRect", { x: 3.8, y: 1.55, w: 3.6, h: 0.5, rectRadius: 0.08, fill: { color: STEEL_TINT }, line: { type: "none" } });
    s.addText("config.py 読み込み（設定を反映）", { x: 3.8, y: 1.55, w: 3.6, h: 0.5, align: "center", valign: "middle", fontFace: FONT_BODY, fontSize: 11.5, bold: true, color: TEXT_DARK, margin: 0 });

    // ---- Loop container ----
    const loopX = 0.6, loopY = 2.2, loopW = 12.13, loopH = 2.35;
    s.addShape("roundRect", { x: loopX, y: loopY, w: loopW, h: loopH, rectRadius: 0.14, fill: { color: CARD_BG }, line: { type: "none" } });
    s.addText("🔁  メインループ（1秒間に何度も繰り返す）", {
      x: loopX + 0.3, y: loopY + 0.15, w: loopW - 0.6, h: 0.3,
      fontFace: FONT_BODY, fontSize: 12, bold: true, color: TEXT_DARK, margin: 0,
    });

    const col0 = 0.9, boxW = 2.65, colGap = 0.3, rowY1 = loopY + 0.55, rowH = 0.85;
    const colX = (i) => col0 + i * (boxW + colGap);
    const colCenter = (i) => colX(i) + boxW / 2;

    const loopBoxes = [
      { t: "センサー取得", sub: "ultrasonic.py / camera.py / lidar.py", fill: CYAN_TINT },
      { t: "planner.py", sub: "判断（steering, throttle決定）", fill: ORANGE_TINT },
      { t: "motor.py", sub: "操作（PWM出力）", fill: STEEL_TINT },
      { t: "記録（任意）", sub: "record_manager", fill: WHITE, border: true },
    ];
    loopBoxes.forEach((b, i) => {
      const x = colX(i);
      s.addShape("roundRect", {
        x, y: rowY1, w: boxW, h: rowH, rectRadius: 0.08,
        fill: { color: b.fill }, line: b.border ? { color: "D6DAE4", width: 1 } : { type: "none" },
      });
      s.addText(b.t, { x: x + 0.12, y: rowY1 + 0.12, w: boxW - 0.24, h: 0.35, fontFace: FONT_HEAD, fontSize: 12.5, bold: true, color: TEXT_DARK, margin: 0 });
      s.addText(b.sub, { x: x + 0.12, y: rowY1 + 0.46, w: boxW - 0.24, h: 0.35, fontFace: FONT_BODY, fontSize: 8.8, color: MUTED, margin: 0, lineSpacingMultiple: 1.05 });
      if (i < loopBoxes.length - 1) {
        s.addText("→", { x: x + boxW, y: rowY1, w: colGap, h: rowH, align: "center", valign: "middle", fontFace: FONT_BODY, fontSize: 15, bold: true, color: MUTED, margin: 0 });
      }
    });

    // loop-back elbow: last box -> first box (solid orange)
    const elbowY = rowY1 + rowH + 0.35;
    diagLine(s, colCenter(3), rowY1 + rowH, colCenter(3), elbowY, { color: ORANGE, width: 2 });
    diagLine(s, colCenter(0), elbowY, colCenter(3), elbowY, { color: ORANGE, width: 2 });
    diagLine(s, colCenter(0), rowY1 + rowH, colCenter(0), elbowY, { color: ORANGE, width: 2 });
    arrowGlyph(s, colCenter(0), rowY1 + rowH + 0.02, "▲", ORANGE, 12);
    s.addShape("roundRect", { x: colCenter(1) + 0.35, y: elbowY - 0.15, w: 1.3, h: 0.3, rectRadius: 0.15, fill: { color: WHITE }, line: { type: "none" } });
    s.addText("くり返す", { x: colCenter(1) + 0.35, y: elbowY - 0.15, w: 1.3, h: 0.3, align: "center", valign: "middle", fontFace: FONT_BODY, fontSize: 9.5, bold: true, color: ORANGE, margin: 0 });

    // ---- Offline training flow ----
    const offY = loopY + loopH + 0.4;
    s.addText("🎓  学習ループ（オフライン・任意）", {
      x: 0.6, y: offY, w: 8, h: 0.3, fontFace: FONT_BODY, fontSize: 12, bold: true, color: TEXT_DARK, margin: 0,
    });
    const offRowY = offY + 0.35, offRowH = 0.8;
    const offBoxes = [
      { t: "記録データ", sub: "", fill: STEEL_TINT, color: TEXT_DARK },
      { t: "data_viewer", sub: "で確認・整理", fill: CYAN_TINT, color: TEXT_DARK },
      { t: "train_pytorch.py", sub: "で学習", fill: ORANGE_TINT, color: TEXT_DARK },
      { t: "学習済みモデル", sub: "", fill: NAVY, color: WHITE },
    ];
    offBoxes.forEach((b, i) => {
      const x = colX(i);
      s.addShape("roundRect", { x, y: offRowY, w: boxW, h: offRowH, rectRadius: 0.08, fill: { color: b.fill }, line: { type: "none" } });
      s.addText(b.t, { x: x + 0.12, y: offRowY, w: boxW - 0.24, h: offRowH, valign: "middle", align: b.sub ? "left" : "center", fontFace: FONT_HEAD, fontSize: 12, bold: true, color: b.color, margin: 0 });
      if (b.sub) {
        s.addText(b.sub, { x: x + 0.12, y: offRowY + 0.38, w: boxW - 0.24, h: 0.3, fontFace: FONT_BODY, fontSize: 9, color: MUTED, margin: 0 });
      }
      if (i < offBoxes.length - 1) {
        s.addText("→", { x: x + boxW, y: offRowY, w: colGap, h: offRowH, align: "center", valign: "middle", fontFace: FONT_BODY, fontSize: 15, bold: true, color: MUTED, margin: 0 });
      }
    });

    // connector: loop container bottom -> offline flow (dashed, produces data)
    diagLine(s, colCenter(3), loopY + loopH, colCenter(0), offRowY, { color: STEEL_SOFT, width: 1.5, dash: "dash" });
    arrowGlyph(s, colCenter(0) - 0.05, offRowY - 0.02, "▼", STEEL_SOFT, 11);

    // connector: trained model -> feeds back into planner.py inference (dashed, cyan)
    diagLine(s, colCenter(3), offRowY, colCenter(1), rowY1 + rowH, { color: CYAN, width: 1.5, dash: "dash" });
    arrowGlyph(s, colCenter(1), rowY1 + rowH - 0.02, "▲", CYAN, 11);

    s.addShape("roundRect", { x: 0.6, y: offRowY + offRowH + 0.25, w: loopW, h: 0.5, rectRadius: 0.08, fill: { color: NAVY }, line: { type: "none" } });
    s.addText("💡 記録したデータは学習ループへ、学習済みモデルは planner.py の推論(自動走行時)へ ― どちらも任意で、手動運転だけでも走行可能", {
      x: 0.85, y: offRowY + offRowH + 0.25, w: loopW - 0.5, h: 0.5, valign: "middle",
      fontFace: FONT_BODY, fontSize: 10, color: "C7CEDE", margin: 0,
    });

    pageNum(s, 4);
  }

  // =========================================================================
  // Slide 5 — run.py
  // =========================================================================
  {
    const s = pres.addSlide();
    s.background = { color: WHITE };
    eyebrow(s, "01 / run.py");
    slideTitle(s, "run.py ― 全体を動かす指揮者");

    s.addText([
      { text: "python run.py ", options: { bold: true, color: ORANGE, breakLine: true } },
      { text: "を実行すると起動する、走行時のメインプログラム。", options: { color: TEXT_DARK, breakLine: true } },
      { text: "認知・判断・操作・記録の4つの処理を、", options: { color: TEXT_DARK, breakLine: true } },
      { text: "電源が切れるまでひたすら繰り返す。", options: { color: TEXT_DARK } },
    ], {
      x: 0.6, y: 1.85, w: 5.4, h: 1.9,
      fontFace: FONT_BODY, fontSize: 14.5, margin: 0, lineSpacingMultiple: 1.3,
    });

    s.addShape("roundRect", {
      x: 0.6, y: 3.8, w: 5.4, h: 1.85, rectRadius: 0.1,
      fill: { color: NAVY }, line: { type: "none" },
    });
    s.addText([
      { text: "# 認知", options: { breakLine: true } },
      { text: "sensor_data = data_aggregator.update_sensors()", options: { breakLine: true } },
      { text: "# 判断", options: { breakLine: true } },
      { text: "steering, throttle = planner_instance.planning_seaquence(...)", options: { breakLine: true } },
      { text: "# 操作", options: { breakLine: true } },
      { text: "motor_instance.set_steering_pwm_value(steering)" },
    ], {
      x: 0.85, y: 3.95, w: 4.9, h: 1.55,
      fontFace: "Courier New", fontSize: 9.5, color: "8BE9C8", margin: 0, lineSpacingMultiple: 1.15,
    });
    s.addText("実際の run.py 中のコメント表記（簡略化）", {
      x: 0.6, y: 5.72, w: 5.4, h: 0.3,
      fontFace: FONT_BODY, fontSize: 10, italic: true, color: MUTED, margin: 0,
    });

    // right: 4-step vertical timeline
    const steps = [
      { n: "1", t: "センサー値を取得", d: "超音波/LiDAR/カメラ、コントローラーの状態を読む" },
      { n: "2", t: "steering・throttle を決定", d: "手動モードなら人間の入力、自動モードなら planner.py が計算" },
      { n: "3", t: "モーターへ出力", d: "motor.py 経由でPWM信号としてサーボ・ESCへ送る" },
      { n: "4", t: "データを記録（任意）", d: "記録中なら画像・センサー値・操作値を保存し学習に使う" },
    ];
    const tlX = 6.6, tlTop = 1.85, rowH = 1.18;
    s.addShape("line", { x: tlX + 0.28, y: tlTop + 0.15, w: 0, h: rowH * (steps.length - 1) + 0.5, line: { color: "D6DAE4", width: 2 } });
    steps.forEach((st, i) => {
      const y = tlTop + i * rowH;
      s.addShape("ellipse", {
        x: tlX, y, w: 0.56, h: 0.56,
        fill: { color: i === 3 ? STEEL : ORANGE }, line: { type: "none" },
      });
      s.addText(st.n, {
        x: tlX, y, w: 0.56, h: 0.56, align: "center", valign: "middle",
        fontFace: FONT_BODY, fontSize: 14, bold: true, color: WHITE, margin: 0,
      });
      s.addText(st.t, {
        x: tlX + 0.8, y: y - 0.06, w: 5.9, h: 0.35,
        fontFace: FONT_HEAD, fontSize: 15, bold: true, color: TEXT_DARK, margin: 0,
      });
      s.addText(st.d, {
        x: tlX + 0.8, y: y + 0.32, w: 5.9, h: 0.6,
        fontFace: FONT_BODY, fontSize: 11.5, color: MUTED, margin: 0, lineSpacingMultiple: 1.15,
      });
    });

    s.addShape("roundRect", {
      x: 6.6, y: 6.55, w: 6.13, h: 0.55, rectRadius: 0.08,
      fill: { color: CARD_BG }, line: { type: "none" },
    });
    s.addText("💡 コントローラーのSボタンで「手動 → 自動ステアリングのみ → 完全自動」を切替", {
      x: 6.8, y: 6.55, w: 5.8, h: 0.55, valign: "middle",
      fontFace: FONT_BODY, fontSize: 10.5, color: TEXT_DARK, margin: 0,
    });

    pageNum(s, 5);
  }

  // =========================================================================
  // Slide 6 — config.py
  // =========================================================================
  {
    const s = pres.addSlide();
    s.background = { color: WHITE };
    eyebrow(s, "02 / config.py");
    slideTitle(s, "config.py ― 挙動を決める設定書");

    s.addText("プログラムのコードを書き換えなくても、この1ファイルを編集するだけで走行モードや速度、使うセンサーを変更できる。", {
      x: 0.6, y: 1.75, w: 11.9, h: 0.55,
      fontFace: FONT_BODY, fontSize: 13.5, color: TEXT_DARK, margin: 0, lineSpacingMultiple: 1.2,
    });

    // relationship diagram
    const boxY = 2.55, boxH = 0.95;
    s.addShape("roundRect", { x: 0.6, y: boxY, w: 3.6, h: boxH, rectRadius: 0.1, fill: { color: STEEL_TINT }, line: { type: "none" } });
    s.addText([
      { text: "config_default.py", options: { bold: true, color: TEXT_DARK, fontSize: 13, breakLine: true } },
      { text: "デフォルト設定（原本・編集しない）", options: { color: MUTED, fontSize: 10 } },
    ], { x: 0.8, y: boxY, w: 3.2, h: boxH, valign: "middle", fontFace: FONT_BODY, margin: 0, lineSpacingMultiple: 1.05 });

    s.addText("自動コピー →", { x: 4.25, y: boxY, w: 1.55, h: boxH, align: "center", valign: "middle", fontFace: FONT_BODY, fontSize: 11, color: MUTED, margin: 0 });

    s.addShape("roundRect", { x: 5.85, y: boxY, w: 3.6, h: boxH, rectRadius: 0.1, fill: { color: ORANGE_TINT }, line: { type: "none" } });
    s.addText([
      { text: "config.py", options: { bold: true, color: TEXT_DARK, fontSize: 13, breakLine: true } },
      { text: "個人設定（自由に編集OK・git管理外）", options: { color: MUTED, fontSize: 10 } },
    ], { x: 6.05, y: boxY, w: 3.2, h: boxH, valign: "middle", fontFace: FONT_BODY, margin: 0, lineSpacingMultiple: 1.05 });

    s.addText("削除すれば config_default.py から再生成される", {
      x: 9.7, y: boxY, w: 3.0, h: boxH, valign: "middle",
      fontFace: FONT_BODY, fontSize: 10, italic: true, color: MUTED, margin: 0,
    });

    // key settings table
    s.addText("主な設定項目（抜粋）", {
      x: 0.6, y: 3.85, w: 6, h: 0.35, fontFace: FONT_HEAD, fontSize: 15, bold: true, color: TEXT_DARK, margin: 0,
    });
    const rows = [
      ["PLAN", "走行モード", "\"right_left_3\" / \"donkeycar\" / \"nn\" など"],
      ["ACTIVE_SENSORS", "使うセンサー", "[\"ultrasonic\"] / [\"lidar\",\"camera_0\"] など"],
      ["FORWARD_STRAIGHT / CORNER", "速度", "直線用 0.4 ／ カーブ用 0.3（0〜1）"],
      ["MODEL_NAME", "学習済みモデル", "自動走行で読み込むファイル名"],
    ];
    s.addTable(
      [
        [
          { text: "設定名", options: { bold: true, color: WHITE, fill: { color: NAVY } } },
          { text: "意味", options: { bold: true, color: WHITE, fill: { color: NAVY } } },
          { text: "値の例", options: { bold: true, color: WHITE, fill: { color: NAVY } } },
        ],
        ...rows.map(([a, b, c], i) => [
          { text: a, options: { fill: { color: i % 2 ? CARD_BG : WHITE }, fontFace: "Courier New", fontSize: 10.5, color: ORANGE } },
          { text: b, options: { fill: { color: i % 2 ? CARD_BG : WHITE }, fontSize: 11 } },
          { text: c, options: { fill: { color: i % 2 ? CARD_BG : WHITE }, fontSize: 10.5, color: MUTED } },
        ]),
      ],
      { x: 0.6, y: 4.25, w: 8.9, h: 2.15, fontFace: FONT_BODY, color: TEXT_DARK, border: { type: "none" }, autoPage: false,
        colW: [3.0, 2.3, 3.6] }
    );

    // side: mode list card
    s.addShape("roundRect", { x: 9.75, y: 3.85, w: 2.98, h: 2.55, rectRadius: 0.1, fill: { color: CARD_BG }, line: { type: "none" } });
    s.addText("走行モード一覧（抜粋）", {
      x: 9.95, y: 3.98, w: 2.6, h: 0.3, fontFace: FONT_HEAD, fontSize: 12, bold: true, color: TEXT_DARK, margin: 0,
    });
    const modes = ["manual（手動）", "right_left_3（回避）", "wall_follow_pid（壁沿い）", "nn（NN推論）", "donkeycar（CNN）"];
    s.addText(modes.map((m, i) => ({ text: m, options: { bullet: { code: "2022" }, breakLine: i < modes.length - 1, color: TEXT_DARK, fontSize: 10.5 } })), {
      x: 9.95, y: 4.32, w: 2.6, h: 2.0, fontFace: FONT_BODY, margin: 0, paraSpaceAfter: 6,
    });

    pageNum(s, 6);
  }

  // =========================================================================
  // Slide 7 — 認知プログラム群
  // =========================================================================
  {
    const s = pres.addSlide();
    s.background = { color: WHITE };
    eyebrow(s, "03 / ultrasonic.py / camera.py / lidar.py");
    slideTitle(s, "認知 ― センサーで周りを見る");

    s.addText("超音波・LiDARは「ToF（Time of Flight）方式」で、波を発射して反射が戻るまでの時間から距離を計算する。カメラは光を捉えて画像として周囲を記録する。", {
      x: 0.6, y: 1.75, w: 11.9, h: 0.5,
      fontFace: FONT_BODY, fontSize: 13, color: TEXT_DARK, margin: 0, lineSpacingMultiple: 1.2,
    });

    const sensors = [
      { name: "超音波センサー", sub: "ultrasonic.py（HC-SR04）", ic: icon.wave_navy, color: CYAN,
        rows: [["検知角度", "約15度（片側）"], ["検知距離", "2cm〜400cm"], ["精度", "±3mm"], ["コスト", "安価"]] },
      { name: "LiDAR", sub: "lidar.py（YDLIDAR等）", ic: icon.satellite_navy, color: ORANGE,
        rows: [["検知角度", "270〜360度"], ["検知距離", "2cm〜12m"], ["精度", "数mm〜数cm"], ["コスト", "高価"]] },
      { name: "カメラ", sub: "camera.py", ic: icon.camera_navy, color: STEEL,
        rows: [["取得情報", "色・形・テクスチャ"], ["用途", "AI画像認識・物体検知"], ["環境依存", "照明に依存"], ["コスト", "やや高価"]] },
    ];

    const cardW = 3.75, gap = 0.35, top = 2.55, cardH = 3.9;
    const left = (13.333 - (3 * cardW + 2 * gap)) / 2;
    sensors.forEach((sn, i) => {
      const x = left + i * (cardW + gap);
      s.addShape("roundRect", { x, y: top, w: cardW, h: cardH, rectRadius: 0.12, fill: { color: CARD_BG }, line: { type: "none" } });
      iconCircle(s, sn.ic, x + cardW / 2, top + 0.75, 1.0, sn.color === STEEL ? STEEL_TINT : sn.color === CYAN ? CYAN_TINT : ORANGE_TINT);
      s.addText(sn.name, {
        x: x + 0.2, y: top + 1.35, w: cardW - 0.4, h: 0.35, align: "center",
        fontFace: FONT_HEAD, fontSize: 15.5, bold: true, color: TEXT_DARK, margin: 0,
      });
      s.addText(sn.sub, {
        x: x + 0.2, y: top + 1.68, w: cardW - 0.4, h: 0.3, align: "center",
        fontFace: FONT_BODY, fontSize: 10, color: MUTED, margin: 0,
      });
      const rowsTop = top + 2.15;
      sn.rows.forEach((r, ri) => {
        const ry = rowsTop + ri * 0.4;
        s.addText(r[0], { x: x + 0.3, y: ry, w: 1.4, h: 0.36, fontFace: FONT_BODY, fontSize: 10.5, color: MUTED, margin: 0, valign: "middle" });
        s.addText(r[1], { x: x + 1.65, y: ry, w: cardW - 1.9, h: 0.36, fontFace: FONT_BODY, fontSize: 10.5, bold: true, color: TEXT_DARK, margin: 0, valign: "middle" });
      });
    });

    pageNum(s, 7);
  }

  // =========================================================================
  // Slide 8 — planner.py
  // =========================================================================
  {
    const s = pres.addSlide();
    s.background = { color: WHITE };
    eyebrow(s, "04 / planner.py");
    slideTitle(s, "planner.py ― 走り方を決める頭脳");

    s.addText("認知で得たセンサー値をもとに、ステアリングとスロットルを決める。判断方式は大きく2種類。出力は常に -1〜1 の統一形式。", {
      x: 0.6, y: 1.75, w: 11.9, h: 0.5,
      fontFace: FONT_BODY, fontSize: 13, color: TEXT_DARK, margin: 0, lineSpacingMultiple: 1.2,
    });

    // two method cards (left column, stacked)
    const colX = 0.6, colW = 5.7;
    const m1Y = 2.5, mH = 1.7;
    s.addShape("roundRect", { x: colX, y: m1Y, w: colW, h: mH, rectRadius: 0.1, fill: { color: STEEL_TINT }, line: { type: "none" } });
    s.addText("ルールベース", { x: colX + 0.3, y: m1Y + 0.18, w: colW - 0.6, h: 0.35, fontFace: FONT_HEAD, fontSize: 15, bold: true, color: TEXT_DARK, margin: 0 });
    s.addText("「こういう時はこうする」を人間が明示的に書く方式。right_left_3・wall_follow・wall_follow_pid など。", {
      x: colX + 0.3, y: m1Y + 0.58, w: colW - 0.6, h: 0.55, fontFace: FONT_BODY, fontSize: 11, color: MUTED, margin: 0, lineSpacingMultiple: 1.2,
    });
    s.addText("○ 動作が明確・少ないデータで動く　× 複雑な状況に弱い", {
      x: colX + 0.3, y: m1Y + 1.22, w: colW - 0.6, h: 0.35, fontFace: FONT_BODY, fontSize: 10, italic: true, color: STEEL_SOFT, margin: 0,
    });

    const m2Y = m1Y + mH + 0.3;
    s.addShape("roundRect", { x: colX, y: m2Y, w: colW, h: mH, rectRadius: 0.1, fill: { color: ORANGE_TINT }, line: { type: "none" } });
    s.addText("ニューラルネットワーク", { x: colX + 0.3, y: m2Y + 0.18, w: colW - 0.6, h: 0.35, fontFace: FONT_HEAD, fontSize: 15, bold: true, color: TEXT_DARK, margin: 0 });
    s.addText("人間の運転データを学習し、AIが判断する方式。nn（センサー値）・donkeycar / resnet18（カメラ画像）など。", {
      x: colX + 0.3, y: m2Y + 0.58, w: colW - 0.6, h: 0.55, fontFace: FONT_BODY, fontSize: 11, color: MUTED, margin: 0, lineSpacingMultiple: 1.2,
    });
    s.addText("○ 複雑なパターンに対応　× 大量の学習データが必要", {
      x: colX + 0.3, y: m2Y + 1.22, w: colW - 0.6, h: 0.35, fontFace: FONT_BODY, fontSize: 10, italic: true, color: "B5522A", margin: 0,
    });

    // right: right_left_3 flow diagram
    s.addText("例：right_left_3（3センサー障害物回避）", {
      x: 6.7, y: 2.5, w: 6.0, h: 0.35, fontFace: FONT_HEAD, fontSize: 14, bold: true, color: TEXT_DARK, margin: 0,
    });

    const fx = 6.7, fw = 6.0;
    const box = (y, h, text, fill, textColor) => {
      s.addShape("roundRect", { x: fx, y, w: fw, h, rectRadius: 0.08, fill: { color: fill }, line: { type: "none" } });
      s.addText(text, { x: fx + 0.25, y, w: fw - 0.5, h, valign: "middle", align: "center", fontFace: FONT_BODY, fontSize: 12, bold: true, color: textColor, margin: 0 });
    };
    const arrow = (y) => s.addText("↓", { x: fx, y, w: fw, h: 0.32, align: "center", fontFace: FONT_BODY, fontSize: 16, color: MUTED, margin: 0 });

    box(3.0, 0.55, "前方センサー値を取得（左前・正面・右前）", NAVY, WHITE);
    arrow(3.57);
    box(3.9, 0.55, "いずれかが検知距離より近い？", STEEL_TINT, TEXT_DARK);
    arrow(4.47);

    // branch
    s.addShape("roundRect", { x: fx, y: 4.8, w: fw / 2 - 0.15, h: 0.85, rectRadius: 0.08, fill: { color: CYAN_TINT }, line: { type: "none" } });
    s.addText("左右どちらが\nより開けている？", { x: fx + 0.1, y: 4.8, w: fw / 2 - 0.35, h: 0.85, valign: "middle", align: "center", fontFace: FONT_BODY, fontSize: 10.5, bold: true, color: TEXT_DARK, margin: 0 });
    s.addShape("roundRect", { x: fx + fw / 2 + 0.15, y: 4.8, w: fw / 2 - 0.15, h: 0.85, rectRadius: 0.08, fill: { color: ORANGE_TINT }, line: { type: "none" } });
    s.addText("障害物なし\nそのまま直進", { x: fx + fw / 2 + 0.25, y: 4.8, w: fw / 2 - 0.35, h: 0.85, valign: "middle", align: "center", fontFace: FONT_BODY, fontSize: 10.5, bold: true, color: TEXT_DARK, margin: 0 });

    arrow(5.72);
    box(6.05, 0.55, "開けている側へ旋回 → steering 出力", ORANGE, WHITE);

    pageNum(s, 8);
  }

  // =========================================================================
  // Slide 9 — motor.py
  // =========================================================================
  {
    const s = pres.addSlide();
    s.background = { color: WHITE };
    eyebrow(s, "05 / motor.py");
    slideTitle(s, "motor.py ― 命令を実際の動きに変える");

    s.addText("planner.py が決めた「-1〜1の指示値」を、サーボ・ESCが理解できる「PWM信号」に変換して物理的に車を動かす。", {
      x: 0.6, y: 1.75, w: 11.9, h: 0.5,
      fontFace: FONT_BODY, fontSize: 13, color: TEXT_DARK, margin: 0, lineSpacingMultiple: 1.2,
    });

    // PWM waveform (custom shapes)
    s.addText("PWM信号の仕組み（パルス幅で角度・速度を指定）", {
      x: 0.6, y: 2.45, w: 6, h: 0.32, fontFace: FONT_HEAD, fontSize: 13.5, bold: true, color: TEXT_DARK, margin: 0,
    });
    const wY = 3.0, wX = 0.6, wW = 5.6;
    s.addShape("line", { x: wX, y: wY + 0.7, w: wW, h: 0, line: { color: "D6DAE4", width: 1 } });
    // pulses: baseline - up - down pattern x2
    const pulses = [
      { x: wX + 0.2, pw: 0.55 },
      { x: wX + 2.1, pw: 0.85 },
      { x: wX + 4.2, pw: 1.15 },
    ];
    const labels = ["短い＝左最大 / 後退", "中間＝中央 / 停止", "長い＝右最大 / 前進"];
    pulses.forEach((p, i) => {
      s.addShape("line", { x: p.x, y: wY, w: 0, h: 0.7, line: { color: ORANGE, width: 2 } });
      s.addShape("line", { x: p.x, y: wY, w: p.pw, h: 0, line: { color: ORANGE, width: 2 } });
      s.addShape("line", { x: p.x + p.pw, y: wY, w: 0, h: 0.7, line: { color: ORANGE, width: 2 } });
      s.addText(labels[i], { x: p.x - 0.3, y: wY + 0.78, w: 1.9, h: 0.55, align: "center", fontFace: FONT_BODY, fontSize: 9.5, color: MUTED, margin: 0, lineSpacingMultiple: 1.1 });
    });

    // value mapping table
    s.addText("正規化値 → PWM値の対応（例：中央370, 幅80）", {
      x: 0.6, y: 4.75, w: 6, h: 0.3, fontFace: FONT_HEAD, fontSize: 13, bold: true, color: TEXT_DARK, margin: 0,
    });
    const mapRows = [
      ["-1.0（左最大）", "290"],
      ["0.0（直進）", "370"],
      ["+1.0（右最大）", "450"],
    ];
    s.addTable(
      [
        [{ text: "ステアリング指示値", options: { bold: true, color: WHITE, fill: { color: NAVY }, fontSize: 10.5 } }, { text: "PWM値", options: { bold: true, color: WHITE, fill: { color: NAVY }, fontSize: 10.5 } }],
        ...mapRows.map(([a, b], i) => [
          { text: a, options: { fill: { color: i % 2 ? CARD_BG : WHITE }, fontSize: 10.5 } },
          { text: b, options: { fill: { color: i % 2 ? CARD_BG : WHITE }, fontSize: 10.5, bold: true, color: ORANGE } },
        ]),
      ],
      { x: 0.6, y: 5.1, w: 5.6, h: 1.35, fontFace: FONT_BODY, color: TEXT_DARK, border: { type: "none" }, autoPage: false, colW: [3.6, 2.0] }
    );

    // right: hardware chain card
    s.addShape("roundRect", { x: 6.7, y: 2.45, w: 6.0, h: 4.0, rectRadius: 0.12, fill: { color: CARD_BG }, line: { type: "none" } });
    s.addText("ハードウェアの流れ", { x: 6.95, y: 2.65, w: 5.5, h: 0.35, fontFace: FONT_HEAD, fontSize: 14, bold: true, color: TEXT_DARK, margin: 0 });

    const chain = ["Raspberry Pi / Jetson", "PCA9685（PWMコントローラ・I2C接続）", "ステアリングサーボ ／ ESC（モーター）"];
    chain.forEach((c, i) => {
      const y = 3.15 + i * 0.95;
      s.addShape("roundRect", { x: 7.0, y, w: 5.4, h: 0.6, rectRadius: 0.08, fill: { color: WHITE }, line: { color: "E1E5EE", width: 1 } });
      s.addText(c, { x: 7.2, y, w: 5.0, h: 0.6, valign: "middle", fontFace: FONT_BODY, fontSize: 12, bold: true, color: TEXT_DARK, margin: 0 });
      if (i < chain.length - 1) {
        s.addText("↓", { x: 7.0, y: y + 0.6, w: 5.4, h: 0.35, align: "center", fontFace: FONT_BODY, fontSize: 14, color: MUTED, margin: 0 });
      }
    });
    s.addText("PCA9685が正確なPWM信号を専用ハードウェアで生成するため、CPUの負荷を増やさず安定して動かせる。", {
      x: 7.0, y: 6.05, w: 5.4, h: 0.35, fontFace: FONT_BODY, fontSize: 9.5, italic: true, color: MUTED, margin: 0, lineSpacingMultiple: 1.1,
    });

    pageNum(s, 9);
  }

  // =========================================================================
  // Slide 10 — train_pytorch.py / data_viewer
  // =========================================================================
  {
    const s = pres.addSlide();
    s.background = { color: WHITE };
    eyebrow(s, "06 / train_pytorch.py / data_viewer");
    slideTitle(s, "train_pytorch.py ― 運転を学習する");

    s.addText("AIに運転を学習させるための一連の流れ。ルールベースでは対応しきれない状況にも対応できるようになる。", {
      x: 0.6, y: 1.75, w: 11.9, h: 0.5,
      fontFace: FONT_BODY, fontSize: 13, color: TEXT_DARK, margin: 0, lineSpacingMultiple: 1.2,
    });

    const flow = [
      { n: "1", t: "手動走行", d: "人がコントローラーで操作し、\nセンサー値・画像・操作値を記録", ic: icon.gamepad_navy, color: CYAN_TINT },
      { n: "2", t: "データ確認", d: "data_viewer（Webアプリ）で\n収集データを確認・クレンジング", ic: icon.filter_white, color: STEEL_TINT },
      { n: "3", t: "学習", d: "train_pytorch.py で\nニューラルネットを学習", ic: icon.graduation_white, color: ORANGE_TINT },
      { n: "4", t: "自動走行", d: "学習済みモデルを使って\n自動運転（donkeycar等）", ic: icon.rocket_white, color: CYAN_TINT },
    ];

    const cardW = 2.75, gap = 0.35, top = 2.6, cardH = 3.1;
    const left = (13.333 - (4 * cardW + 3 * gap)) / 2;
    flow.forEach((f, i) => {
      const x = left + i * (cardW + gap);
      s.addShape("roundRect", { x, y: top, w: cardW, h: cardH, rectRadius: 0.12, fill: { color: CARD_BG }, line: { type: "none" } });
      s.addShape("ellipse", { x: x + 0.15, y: top + 0.15, w: 0.4, h: 0.4, fill: { color: ORANGE }, line: { type: "none" } });
      s.addText(f.n, { x: x + 0.15, y: top + 0.15, w: 0.4, h: 0.4, align: "center", valign: "middle", fontFace: FONT_BODY, fontSize: 12, bold: true, color: WHITE, margin: 0 });
      iconCircle(s, f.ic, x + cardW / 2, top + 1.15, 0.95, f.color);
      s.addText(f.t, { x: x + 0.2, y: top + 1.75, w: cardW - 0.4, h: 0.35, align: "center", fontFace: FONT_HEAD, fontSize: 14, bold: true, color: TEXT_DARK, margin: 0 });
      s.addText(f.d, { x: x + 0.2, y: top + 2.12, w: cardW - 0.4, h: 0.85, align: "center", fontFace: FONT_BODY, fontSize: 10, color: MUTED, margin: 0, lineSpacingMultiple: 1.15 });
      if (i < flow.length - 1) {
        s.addText("→", { x: x + cardW + 0.02, y: top + cardH / 2 - 0.3, w: gap - 0.04, h: 0.6, align: "center", valign: "middle", fontFace: FONT_BODY, fontSize: 20, bold: true, color: MUTED, margin: 0 });
      }
    });

    s.addShape("roundRect", { x: left, y: top + cardH + 0.3, w: 4 * cardW + 3 * gap, h: 0.55, rectRadius: 0.08, fill: { color: NAVY }, line: { type: "none" } });
    s.addText("💡 カメラ画像を使うモデル（donkeycar / resnet18等）の学習には annotation_training_d2j との連携が必要", {
      x: left + 0.25, y: top + cardH + 0.3, w: 4 * cardW + 3 * gap - 0.5, h: 0.55, valign: "middle",
      fontFace: FONT_BODY, fontSize: 10.5, color: "C7CEDE", margin: 0,
    });

    pageNum(s, 10);
  }

  // =========================================================================
  // Slide 11 — 高度な機能マップ
  // =========================================================================
  {
    const s = pres.addSlide();
    s.background = { color: WHITE };
    eyebrow(s, "Advanced Features ― まだまだ広い機能の世界");
    slideTitle(s, "高度な機能マップ");

    // stat callouts
    const statY = 1.85, statW = 3.5, statH = 1.15, statGap = 0.4, statLeft = 0.6;
    const stats = [
      { big: "473", label: "config.py の設定項目数" },
      { big: "15〜20%", label: "これまでの基本解説でカバーした範囲" },
    ];
    stats.forEach((st, i) => {
      const x = statLeft + i * (statW + statGap);
      s.addShape("roundRect", { x, y: statY, w: statW, h: statH, rectRadius: 0.1, fill: { color: NAVY }, line: { type: "none" } });
      s.addText(st.big, { x: x + 0.25, y: statY + 0.12, w: statW - 0.5, h: 0.6, fontFace: FONT_HEAD, fontSize: 30, bold: true, color: ORANGE, margin: 0 });
      s.addText(st.label, { x: x + 0.25, y: statY + 0.74, w: statW - 0.5, h: 0.35, fontFace: FONT_BODY, fontSize: 10.5, color: "C7CEDE", margin: 0 });
    });
    s.addText("残りの大部分は、本格的なレース競技向けの高度な自律走行技術。ここから5つのジャンルを見ていく。", {
      x: statLeft + 2 * statW + statGap + 0.3, y: statY, w: 12.73 - (statLeft + 2 * statW + statGap + 0.3), h: statH,
      valign: "middle", fontFace: FONT_BODY, fontSize: 12.5, color: TEXT_DARK, margin: 0, lineSpacingMultiple: 1.25,
    });

    const advCards = [
      { name: "自己位置推定", sub: "SLAM / VSLAM / ArUco / AMCL", ic: icon.map_navy, color: CYAN_TINT, page: "12" },
      { name: "経路追従・最適制御", sub: "pure pursuit / MPC / MPPI", ic: icon.route_navy, color: ORANGE_TINT, page: "13" },
      { name: "物体検知", sub: "YOLO", ic: icon.crosshairs_navy, color: STEEL_TINT, page: "14" },
      { name: "安全機構", sub: "ControlArbiter", ic: icon.shield_navy, color: CYAN_TINT, page: "15" },
      { name: "強化学習シミュレーター", sub: "togikaidrive-sim", ic: icon.flask_navy, color: ORANGE_TINT, page: "16" },
    ];
    const cardW = 2.3, cardH = 3.15, gap = 0.28, top = 3.4;
    const left = (13.333 - (5 * cardW + 4 * gap)) / 2;
    advCards.forEach((c, i) => {
      const x = left + i * (cardW + gap);
      s.addShape("roundRect", { x, y: top, w: cardW, h: cardH, rectRadius: 0.12, fill: { color: CARD_BG }, line: { type: "none" } });
      iconCircle(s, c.ic, x + cardW / 2, top + 0.75, 0.95, c.color);
      s.addText(c.name, {
        x: x + 0.15, y: top + 1.35, w: cardW - 0.3, h: 0.65, align: "center",
        fontFace: FONT_HEAD, fontSize: 13, bold: true, color: TEXT_DARK, margin: 0, lineSpacingMultiple: 1.05,
      });
      s.addText(c.sub, {
        x: x + 0.15, y: top + 2.0, w: cardW - 0.3, h: 0.7, align: "center",
        fontFace: FONT_BODY, fontSize: 9.5, color: MUTED, margin: 0, lineSpacingMultiple: 1.15,
      });
      s.addText(`p.${c.page}`, {
        x: x + 0.15, y: top + cardH - 0.4, w: cardW - 0.3, h: 0.3, align: "center",
        fontFace: FONT_BODY, fontSize: 9, bold: true, color: MUTED, margin: 0,
      });
    });

    pageNum(s, 11);
  }

  // =========================================================================
  // Slide 12 — 自己位置推定(SLAM/VSLAM/ArUco/AMCL)
  // =========================================================================
  {
    const s = pres.addSlide();
    s.background = { color: WHITE };
    eyebrow(s, "12 / localization/ (SLAM / VSLAM / ArUco / AMCL)");
    slideTitle(s, "自己位置推定 ― 「今どこにいるか」を知る");

    s.addText("経路追従や最適制御を行うには、まず「自分が地図上のどこに・どの向きにいるか」を推定する必要がある。用途に応じて4種類の方式が用意されている。", {
      x: 0.6, y: 1.75, w: 11.9, h: 0.55,
      fontFace: FONT_BODY, fontSize: 13, color: TEXT_DARK, margin: 0, lineSpacingMultiple: 1.2,
    });

    const rows = [
      ["lidar_slam", "2D LiDAR", "不要(numpy/scipyのみ)", "占有格子地図 + スキャンマッチング(自前実装)"],
      ["slam_toolbox", "2D LiDAR", "ROS2必須", "ポーズグラフSLAM。ループクロージャ対応"],
      ["amcl", "LiDAR + 事前地図", "ROS2必須", "パーティクルフィルタで保存済み地図に対して自己位置推定"],
      ["visual_slam (VSLAM)", "RealSense D435i", "ROS2 + Isaac ROS必須", "cuVSLAM(視覚慣性オドメトリ)。vio/mapping/localizeの3モード"],
      ["aruco", "外部の俯瞰カメラ", "UDP受信のみ(ROS不要)", "天井/コース脇のカメラでARマーカーを検出し三角測量"],
    ];
    s.addTable(
      [
        ["バックエンド", "使用センサー", "必要環境", "方式"].map(t => ({
          text: t, options: { bold: true, color: WHITE, fill: { color: NAVY }, fontSize: 10.5 },
        })),
        ...rows.map((r, i) => r.map((cell, ci) => ({
          text: cell,
          options: {
            fill: { color: i % 2 ? CARD_BG : WHITE },
            fontSize: 10, bold: ci === 0, color: ci === 0 ? ORANGE : TEXT_DARK,
          },
        }))),
      ],
      { x: 0.6, y: 2.5, w: 12.13, h: 2.9, fontFace: FONT_BODY, border: { type: "none" }, autoPage: false,
        colW: [2.3, 2.5, 2.8, 4.53] }
    );

    s.addShape("roundRect", { x: 0.6, y: 5.7, w: 12.13, h: 0.95, rectRadius: 0.1, fill: { color: NAVY }, line: { type: "none" } });
    s.addText([
      { text: "💡 「map frame」と「odom frame」の違い： ", options: { bold: true, color: ORANGE, breakLine: true } },
      { text: "aruco / lidar_slam / slam_toolbox は絶対座標(map)を返すが、VSLAM は単体では相対座標(odom)止まり。経路追従には絶対座標が必要なため、VSLAMは VSLAM_MODE=\"localize\" で使う。", options: { color: "C7CEDE" } },
    ], {
      x: 0.85, y: 5.82, w: 11.6, h: 0.75, fontFace: FONT_BODY, fontSize: 10.5, margin: 0, lineSpacingMultiple: 1.2,
    });

    pageNum(s, 12);
  }

  // =========================================================================
  // Slide 13 — 経路追従・最適制御
  // =========================================================================
  {
    const s = pres.addSlide();
    s.background = { color: WHITE };
    eyebrow(s, "13 / localization/ (path_nav / waypoint_nav / mpc / mppi)");
    slideTitle(s, "経路追従 ― 自己位置を使って正確に走る");

    s.addText("自己位置が分かれば、あらかじめ記録した経路や目標点に向かって走れる。シンプルな幾何学的追従から、数手先を予測する最適制御まで、精度と計算コストが異なる複数の方式がある。", {
      x: 0.6, y: 1.75, w: 11.9, h: 0.6,
      fontFace: FONT_BODY, fontSize: 13, color: TEXT_DARK, margin: 0, lineSpacingMultiple: 1.2,
    });

    const steps = [
      { t: "path_nav / waypoint_nav", d: "pure pursuit法。記録した経路や目標点列へ、幾何学的に滑らかに追従する基本形。", color: CYAN_TINT },
      { t: "mpc", d: "非線形モデル予測制御(iLQR)。数手先の動きまで計算し、path_navより精密に追従する上位互換。", color: STEEL_TINT },
      { t: "mppi", d: "サンプリングベースの最適制御。経路追従に加え、LiDARで検知した障害物回避もコストに織り込む。", color: ORANGE_TINT },
      { t: "mppi_local", d: "地図も自己位置も使わない発展形。LiDAR点群だけを見て、その場で開いた空間へ向かう。", color: NAVY, textWhite: true },
    ];
    const rowTop = 2.55, rowH = 1.05, rowW = 12.13, rowX = 0.6;
    steps.forEach((st, i) => {
      const y = rowTop + i * (rowH + 0.15);
      s.addShape("roundRect", { x: rowX, y, w: rowW, h: rowH, rectRadius: 0.1, fill: { color: st.color }, line: { type: "none" } });
      s.addText(`STEP ${i + 1}`, {
        x: rowX + 0.3, y: y + 0.15, w: 1.6, h: 0.3, fontFace: FONT_BODY, fontSize: 9.5, bold: true,
        color: st.textWhite ? ORANGE : ORANGE, margin: 0, charSpacing: 1,
      });
      s.addText(st.t, {
        x: rowX + 0.3, y: y + 0.42, w: 3.2, h: 0.5, fontFace: FONT_HEAD, fontSize: 15, bold: true,
        color: st.textWhite ? WHITE : TEXT_DARK, margin: 0,
      });
      s.addText(st.d, {
        x: rowX + 3.7, y, w: rowW - 4.0, h: rowH, valign: "middle", fontFace: FONT_BODY, fontSize: 11,
        color: st.textWhite ? "C7CEDE" : MUTED, margin: 0, lineSpacingMultiple: 1.2,
      });
      if (i < steps.length - 1) {
        s.addText("↓", { x: rowX, y: y + rowH, w: 1.2, h: 0.15, align: "center", fontFace: FONT_BODY, fontSize: 11, color: MUTED, margin: 0 });
      }
    });

    pageNum(s, 13);
  }

  // =========================================================================
  // Slide 14 — YOLOによる物体検知
  // =========================================================================
  {
    const s = pres.addSlide();
    s.background = { color: WHITE };
    eyebrow(s, "14 / yolo_detection.py");
    slideTitle(s, "YOLO ― カメラで物体を見分ける");

    s.addText("カメラ画像に写る物体(標識・障害物など)をYOLOで検知し、結果を3つの方法で走行に活かす。config.py の USE_YOLO_* フラグで個別にON/OFFできる。", {
      x: 0.6, y: 1.75, w: 11.9, h: 0.55,
      fontFace: FONT_BODY, fontSize: 13, color: TEXT_DARK, margin: 0, lineSpacingMultiple: 1.2,
    });

    const uses = [
      { t: "ルールで操作を上書き", d: "検知したクラスに応じて、あらかじめ決めたステアリング補正・減速ルールを適用する(例: 停止標識を見たら減速)。", ic: icon.sliders_navy, color: CYAN_TINT },
      { t: "モデルを自動で切替", d: "検知した物体の種類に応じて、使用する走行モデル自体を切り替える。計算負荷を抑えるため数フレームに1回だけ実行。", ic: icon.brain_navy, color: ORANGE_TINT },
      { t: "物体追従・回避", d: "検知した箱(バウンディングボックス)の画面中心からのズレに応じて、比例制御でステアリングを補正する。", ic: icon.crosshairs_navy, color: STEEL_TINT },
    ];
    const cardW = 3.75, gap = 0.35, top = 2.65, cardH = 3.5;
    const left = (13.333 - (3 * cardW + 2 * gap)) / 2;
    uses.forEach((u, i) => {
      const x = left + i * (cardW + gap);
      s.addShape("roundRect", { x, y: top, w: cardW, h: cardH, rectRadius: 0.12, fill: { color: CARD_BG }, line: { type: "none" } });
      iconCircle(s, u.ic, x + cardW / 2, top + 0.85, 1.05, u.color);
      s.addText(`0${i + 1}  ${u.t}`, {
        x: x + 0.25, y: top + 1.55, w: cardW - 0.5, h: 0.55, align: "center",
        fontFace: FONT_HEAD, fontSize: 14, bold: true, color: TEXT_DARK, margin: 0, lineSpacingMultiple: 1.05,
      });
      s.addText(u.d, {
        x: x + 0.3, y: top + 2.15, w: cardW - 0.6, h: 1.2, align: "center",
        fontFace: FONT_BODY, fontSize: 10.5, color: MUTED, margin: 0, lineSpacingMultiple: 1.25,
      });
    });

    s.addShape("roundRect", { x: left, y: top + cardH + 0.25, w: 3 * cardW + 2 * gap, h: 0.5, rectRadius: 0.08, fill: { color: CARD_BG }, line: { type: "none" } });
    s.addText("💡 yolo11n〜yolo11x はモデルサイズの違い(nが最速・軽量、xが最高精度・低速)", {
      x: left + 0.25, y: top + cardH + 0.25, w: 3 * cardW + 2 * gap - 0.5, h: 0.5, valign: "middle",
      fontFace: FONT_BODY, fontSize: 10.5, color: TEXT_DARK, margin: 0,
    });

    pageNum(s, 14);
  }

  // =========================================================================
  // Slide 15 — ControlArbiter(安全弁)
  // =========================================================================
  {
    const s = pres.addSlide();
    s.background = { color: WHITE };
    eyebrow(s, "15 / arbiter.py");
    slideTitle(s, "ControlArbiter ― 判断を二重チェックする安全弁");

    s.addText("planner.py が出した判断(steering, throttle)を、状況に応じて上書きできる「安全弁」。planner.py の内部から毎フレーム呼び出される、走行ロジックの裏方。", {
      x: 0.6, y: 1.75, w: 11.9, h: 0.55,
      fontFace: FONT_BODY, fontSize: 13, color: TEXT_DARK, margin: 0, lineSpacingMultiple: 1.2,
    });

    // flow: planner -> arbiter -> motor with branch conditions
    const fx = 0.6, fw = 5.4, fTop = 2.6;
    const box = (y, h, text, fill, textColor) => {
      s.addShape("roundRect", { x: fx, y, w: fw, h, rectRadius: 0.08, fill: { color: fill }, line: { type: "none" } });
      s.addText(text, { x: fx + 0.25, y, w: fw - 0.5, h, valign: "middle", align: "center", fontFace: FONT_BODY, fontSize: 12.5, bold: true, color: textColor, margin: 0 });
    };
    box(fTop, 0.6, "planner.py が主判断(steering, throttle)を計算", NAVY, WHITE);
    s.addText("↓", { x: fx, y: fTop + 0.6, w: fw, h: 0.3, align: "center", fontFace: FONT_BODY, fontSize: 16, color: MUTED, margin: 0 });
    box(fTop + 0.9, 0.6, "ControlArbiter.arbitrate()", ORANGE, WHITE);
    s.addText("↓", { x: fx, y: fTop + 1.5, w: fw, h: 0.3, align: "center", fontFace: FONT_BODY, fontSize: 16, color: MUTED, margin: 0 });
    box(fTop + 1.8, 0.6, "motor.py へ出力(必要なら上書き済み)", STEEL, WHITE);

    s.addText("3つの発動モード(ARBITER_MODE)", {
      x: 6.7, y: 2.5, w: 6.0, h: 0.35, fontFace: FONT_HEAD, fontSize: 14, bold: true, color: TEXT_DARK, margin: 0,
    });
    const modes = [
      { t: "fallback", d: "自己位置推定の信頼度が下がったら、副プラン(例: カメラCNN)へ自動切替", color: CYAN_TINT },
      { t: "events", d: "経路からのズレを監視し、逸脱していたら副プランへ切替、または緊急停止", color: ORANGE_TINT },
      { t: "obstacle", d: "LiDARが前方の狭い範囲に障害物を検知したら副プラン(例: ローカルMPPI回避)へ切替。ただし直進に近い時のみ判定し、コーナリング中の誤反応を避ける", color: STEEL_TINT },
    ];
    modes.forEach((m, i) => {
      const y = 2.95 + i * 1.15;
      s.addShape("roundRect", { x: 6.7, y, w: 6.03, h: 1.0, rectRadius: 0.08, fill: { color: m.color }, line: { type: "none" } });
      s.addText(m.t, { x: 6.95, y: y + 0.1, w: 5.5, h: 0.3, fontFace: FONT_HEAD, fontSize: 12.5, bold: true, color: TEXT_DARK, margin: 0 });
      s.addText(m.d, { x: 6.95, y: y + 0.42, w: 5.5, h: 0.5, fontFace: FONT_BODY, fontSize: 9.8, color: MUTED, margin: 0, lineSpacingMultiple: 1.15 });
    });

    pageNum(s, 15);
  }

  // =========================================================================
  // Slide 16 — 強化学習シミュレーター
  // =========================================================================
  {
    const s = pres.addSlide();
    s.background = { color: WHITE };
    eyebrow(s, "16 / togikaidrive-sim/");
    slideTitle(s, "togikaidrive-sim ― シミュレーターでAIを鍛える");

    s.addText("実車を使わず、f1tenth_gym(レーシングシミュレーター)上でAIに運転を学習させる、研究レベルの高度な機能。plan=\"rl\" で学習済みポリシーを実車に読み込める。", {
      x: 0.6, y: 1.75, w: 11.9, h: 0.55,
      fontFace: FONT_BODY, fontSize: 13, color: TEXT_DARK, margin: 0, lineSpacingMultiple: 1.2,
    });

    const flow = [
      { n: "1", t: "デモ収集", d: "collect_demos.py\nルールベースplannerが\nシミュレーター内で走行", ic: icon.gamepad_navy, color: CYAN_TINT },
      { n: "2", t: "事前学習", d: "pretrain_bc.py\n模倣学習(Behavioral\nCloning)で土台を作る", ic: icon.database_navy, color: STEEL_TINT },
      { n: "3", t: "強化学習", d: "train_rl.py\nSAC/PPO/TD3で\nポリシーを磨き込む", ic: icon.brain_navy, color: ORANGE_TINT },
      { n: "4", t: "実車で使用", d: "enjoy_rl.py で評価、\nplan=\"rl\" で実車に\n読み込んで走行", ic: icon.rocket_white, color: CYAN_TINT },
    ];
    const cardW = 2.75, gap = 0.35, top = 2.6, cardH = 3.1;
    const left = (13.333 - (4 * cardW + 3 * gap)) / 2;
    flow.forEach((f, i) => {
      const x = left + i * (cardW + gap);
      s.addShape("roundRect", { x, y: top, w: cardW, h: cardH, rectRadius: 0.12, fill: { color: CARD_BG }, line: { type: "none" } });
      s.addShape("ellipse", { x: x + 0.15, y: top + 0.15, w: 0.4, h: 0.4, fill: { color: ORANGE }, line: { type: "none" } });
      s.addText(f.n, { x: x + 0.15, y: top + 0.15, w: 0.4, h: 0.4, align: "center", valign: "middle", fontFace: FONT_BODY, fontSize: 12, bold: true, color: WHITE, margin: 0 });
      iconCircle(s, f.ic, x + cardW / 2, top + 1.15, 0.95, f.color);
      s.addText(f.t, { x: x + 0.2, y: top + 1.75, w: cardW - 0.4, h: 0.35, align: "center", fontFace: FONT_HEAD, fontSize: 14, bold: true, color: TEXT_DARK, margin: 0 });
      s.addText(f.d, { x: x + 0.2, y: top + 2.12, w: cardW - 0.4, h: 0.85, align: "center", fontFace: FONT_BODY, fontSize: 9.5, color: MUTED, margin: 0, lineSpacingMultiple: 1.15 });
      if (i < flow.length - 1) {
        s.addText("→", { x: x + cardW + 0.02, y: top + cardH / 2 - 0.3, w: gap - 0.04, h: 0.6, align: "center", valign: "middle", fontFace: FONT_BODY, fontSize: 20, bold: true, color: MUTED, margin: 0 });
      }
    });

    s.addShape("roundRect", { x: left, y: top + cardH + 0.3, w: 4 * cardW + 3 * gap, h: 0.55, rectRadius: 0.08, fill: { color: NAVY }, line: { type: "none" } });
    s.addText("💡 観測はLiDAR108本(ダウンサンプリング済み)+速度の計109次元ベクトル。実車と同じLiDAR構成なら、シムで学習したポリシーがそのまま活きる", {
      x: left + 0.25, y: top + cardH + 0.3, w: 4 * cardW + 3 * gap - 0.5, h: 0.55, valign: "middle",
      fontFace: FONT_BODY, fontSize: 10, color: "C7CEDE", margin: 0,
    });

    pageNum(s, 16);
  }

  // =========================================================================
  // Slide 17 — まとめ
  // =========================================================================
  {
    const s = pres.addSlide();
    s.background = { color: NAVY };

    s.addShape("ellipse", { x: -2.5, y: 4.5, w: 7, h: 7, fill: { type: "none" }, line: { color: STEEL_SOFT, width: 1.2 } });

    eyebrow(s, "Summary", { color: CYAN, y: 0.55 });
    s.addText("まとめ ― なぜこの設計なのか", {
      x: 0.6, y: 0.9, w: 11, h: 0.7, fontFace: FONT_HEAD, fontSize: 30, bold: true, color: WHITE, margin: 0,
    });

    const points = [
      { ic: icon.eye, t: "役割がはっきり分離", d: "認知(センサー)・判断(planner)・操作(motor)が独立しているので、どこを直せばいいか分かりやすい" },
      { ic: icon.sliders_navy, t: "config.py だけ触ればいい", d: "プログラムを書けなくても、速度やモード選びは設定ファイルの数値・文字を変えるだけで調整できる" },
      { ic: icon.brain, t: "ルールからAIまで選べる", d: "シンプルなルールベースから、学習させたニューラルネットまで、走行モードを切り替えて試せる" },
      { ic: icon.rocket_white, t: "段階的に慣れていける", d: "ultrasonic.py → motor.py → run.py の順にクイックスタートで動作確認しながら理解できる" },
    ];

    const cardW = 5.6, cardH = 1.85, gx = 0.4, gy = 0.35, top = 2.05;
    const left = (13.333 - (2 * cardW + gx)) / 2;
    points.forEach((p, i) => {
      const col = i % 2, row = Math.floor(i / 2);
      const x = left + col * (cardW + gx);
      const y = top + row * (cardH + gy);
      s.addShape("roundRect", { x, y, w: cardW, h: cardH, rectRadius: 0.12, fill: { color: STEEL }, line: { type: "none" } });
      iconCircle(s, p.ic, x + 0.8, y + cardH / 2, 0.85, NAVY);
      s.addText(p.t, { x: x + 1.4, y: y + 0.25, w: cardW - 1.6, h: 0.4, fontFace: FONT_HEAD, fontSize: 15, bold: true, color: WHITE, margin: 0 });
      s.addText(p.d, { x: x + 1.4, y: y + 0.68, w: cardW - 1.6, h: 1.0, fontFace: FONT_BODY, fontSize: 10.5, color: "C7CEDE", margin: 0, lineSpacingMultiple: 1.25 });
    });

    s.addText([
      { text: "次の一歩：  ", options: { bold: true, color: ORANGE } },
      { text: "python ultrasonic.py → python motor.py → python run.py の順に動かして、自分のミニカーで体験してみよう", options: { color: "C7CEDE" } },
    ], {
      x: left, y: top + 2 * cardH + gy + 0.15, w: 2 * cardW + gx, h: 0.5,
      fontFace: FONT_BODY, fontSize: 12.5, margin: 0,
    });

    pageNum(s, 17, STEEL_SOFT);
  }

  await pres.writeFile({ fileName: "togikaidrive_overview.pptx" });
  console.log("done");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
