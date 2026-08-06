from pathlib import Path

INDEX_PATH = Path("frontend/index.html")
CSS_PATH = Path("frontend/prompt-complexity.css")
TEST_PATH = Path("tests/test_static_assets.py")

index = INDEX_PATH.read_text(encoding="utf-8")

old_markup = '''        <label for="prompt">Describe the playlist you want</label>
        <textarea id="prompt" maxlength="1950" rows="5" placeholder="A slow-burning road-trip playlist with blues rock, warm guitars and a steady night-drive mood..."></textarea>
        <div id="prompt-complexity" class="prompt-complexity hidden">
          <button
            id="prompt-complexity-trigger"
            class="prompt-complexity-trigger"
            type="button"
            aria-expanded="false"
            aria-controls="prompt-complexity-popover"
            aria-label="Show request complexity"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M4 16a8 8 0 1 1 16 0" />
              <path d="m12 16 4-5" />
              <path d="M7 16h10" />
            </svg>
          </button>

          <div
            id="prompt-complexity-popover"
            class="prompt-complexity-popover"
            role="region"
            aria-labelledby="prompt-complexity-title"
            hidden
          >
            <div class="prompt-complexity-heading">
              <span id="prompt-complexity-title">Request complexity</span>
              <strong id="prompt-complexity-score"></strong>
            </div>
            <div class="prompt-complexity-meter" aria-hidden="true"><span></span></div>
            <p id="prompt-complexity-summary"></p>
            <span id="prompt-clarity" class="prompt-clarity"></span>
          </div>
        </div>'''

new_markup = '''        <div class="prompt-label-row">
          <label for="prompt">Describe the playlist you want</label>
          <div id="prompt-complexity" class="prompt-complexity hidden">
            <button
              id="prompt-complexity-trigger"
              class="prompt-complexity-trigger"
              type="button"
              aria-expanded="false"
              aria-controls="prompt-complexity-popover"
              aria-label="Show request complexity"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                <circle cx="12" cy="12" r="8.5" />
                <path d="M12 10.5v5" />
                <circle class="prompt-complexity-info-dot" cx="12" cy="7.5" r=".8" />
              </svg>
            </button>

            <div
              id="prompt-complexity-popover"
              class="prompt-complexity-popover"
              role="region"
              aria-labelledby="prompt-complexity-title"
              hidden
            >
              <div class="prompt-complexity-heading">
                <span id="prompt-complexity-title">Request complexity</span>
                <strong id="prompt-complexity-score"></strong>
              </div>
              <div class="prompt-complexity-meter" aria-hidden="true"><span></span></div>
              <p id="prompt-complexity-summary"></p>
              <span id="prompt-clarity" class="prompt-clarity"></span>
            </div>
          </div>
        </div>
        <textarea id="prompt" maxlength="1950" rows="5" placeholder="A slow-burning road-trip playlist with blues rock, warm guitars and a steady night-drive mood..."></textarea>'''

if index.count(old_markup) != 1:
    raise SystemExit("Prompt complexity markup does not match the expected current structure")
index = index.replace(old_markup, new_markup, 1)

old_css_ref = '/static/prompt-complexity.css?v=1'
if index.count(old_css_ref) != 1:
    raise SystemExit("Unexpected prompt complexity stylesheet reference")
index = index.replace(old_css_ref, '/static/prompt-complexity.css?v=2', 1)
INDEX_PATH.write_text(index, encoding="utf-8")

CSS_PATH.write_text('''/* Compact prompt analysis trigger and popover. */

.prompt-label-row {
  display: flex;
  align-items: flex-start;
  gap: 3px;
  width: max-content;
  max-width: 100%;
  margin-bottom: 8px;
}

.prompt-label-row > label {
  display: block;
  line-height: 1.25;
}

.prompt-complexity {
  --complexity-hue: 120;
  --complexity-score: 0%;
  --complexity-color: hsl(var(--complexity-hue) 78% 68%);
  position: relative;
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
  margin-top: -5px;
}

.prompt-complexity-trigger {
  display: grid;
  width: 24px;
  height: 24px;
  padding: 0;
  place-items: center;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--complexity-color);
  box-shadow: none;
  transition: background 160ms ease, transform 160ms ease;
}

.prompt-complexity-trigger:hover,
.prompt-complexity-trigger[aria-expanded="true"] {
  background: hsl(var(--complexity-hue) 72% 42% / .11);
}

.prompt-complexity-trigger:hover {
  transform: translateY(-1px);
}

.prompt-complexity-trigger svg {
  width: 12px;
  height: 12px;
  overflow: visible;
}

.prompt-complexity-trigger path,
.prompt-complexity-trigger circle {
  fill: none;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.prompt-complexity-trigger .prompt-complexity-info-dot {
  fill: currentColor;
  stroke: none;
}

.prompt-complexity-popover {
  position: absolute;
  top: calc(100% + 6px);
  left: -4px;
  z-index: 15;
  width: min(320px, calc(100vw - 64px));
  padding: 14px 15px;
  border: 1px solid hsl(var(--complexity-hue) 72% 58% / .28);
  border-radius: 13px;
  background: rgba(8, 11, 27, .97);
  color: var(--text-secondary);
  box-shadow: 0 16px 36px rgba(1, 3, 15, .46);
  backdrop-filter: blur(18px);
  font-size: .78rem;
}

.prompt-complexity-popover::before {
  content: "";
  position: absolute;
  bottom: 100%;
  left: 10px;
  width: 9px;
  height: 9px;
  border-top: 1px solid hsl(var(--complexity-hue) 72% 58% / .28);
  border-left: 1px solid hsl(var(--complexity-hue) 72% 58% / .28);
  background: rgba(8, 11, 27, .97);
  transform: translateY(5px) rotate(45deg);
}

.prompt-complexity-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.prompt-complexity-heading > span {
  color: var(--text-primary);
  font-weight: 750;
}

.prompt-complexity-heading strong {
  color: var(--complexity-color);
  font-size: .8rem;
  font-weight: 800;
}

.prompt-complexity-meter {
  position: relative;
  height: 4px;
  margin: 12px 0 10px;
  border-radius: 999px;
  background: linear-gradient(90deg, #4ade80 0%, #fbbf24 50%, #fb7185 100%);
}

.prompt-complexity-meter span {
  position: absolute;
  top: 50%;
  left: var(--complexity-score);
  width: 10px;
  height: 10px;
  border: 2px solid #f8f7ff;
  border-radius: 50%;
  background: var(--complexity-color);
  box-shadow: 0 0 0 2px rgba(8, 11, 27, .9);
  transform: translate(-50%, -50%);
}

.prompt-complexity-popover p {
  margin: 0;
  line-height: 1.45;
}

.prompt-clarity {
  display: block;
  margin-top: 5px;
  color: #86efac;
}

@media (max-width: 520px) {
  .prompt-complexity-popover {
    width: min(300px, calc(100vw - 56px));
  }
}
''', encoding="utf-8")

tests = TEST_PATH.read_text(encoding="utf-8")
replacements = {
    '<link rel="stylesheet" href="/static/prompt-complexity.css?v=1">': '<link rel="stylesheet" href="/static/prompt-complexity.css?v=2">',
    '    assert "width: 32px" in complexity_style\n    assert "height: 32px" in complexity_style\n    assert "width: 17px" in complexity_style\n': '    assert "width: 24px" in complexity_style\n    assert "height: 24px" in complexity_style\n    assert "width: 12px" in complexity_style\n',
}
for old, new in replacements.items():
    if old not in tests:
        raise SystemExit(f"Expected test fragment not found: {old}")
    tests = tests.replace(old, new, 1)

anchor = '    assert \'id="prompt-complexity-trigger"\' in index\n'
extra = (
    '    assert \'<div class="prompt-label-row">\' in index\n'
    '    assert \'class="prompt-complexity-info-dot"\' in index\n'
    '    assert index.index(\'<div class="prompt-label-row">\') < index.index(\'<textarea id="prompt"\')\n'
)
if anchor not in tests:
    raise SystemExit("Prompt complexity test anchor not found")
tests = tests.replace(anchor, anchor + extra, 1)
TEST_PATH.write_text(tests, encoding="utf-8")
