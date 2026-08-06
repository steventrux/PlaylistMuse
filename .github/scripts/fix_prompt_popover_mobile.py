from pathlib import Path

index_path = Path("frontend/index.html")
index = index_path.read_text(encoding="utf-8")
old_ref = '/static/prompt-complexity.css?v=2'
new_ref = '/static/prompt-complexity.css?v=3'
if index.count(old_ref) != 1:
    raise SystemExit("Unexpected prompt complexity stylesheet reference")
index_path.write_text(index.replace(old_ref, new_ref, 1), encoding="utf-8")

style_path = Path("frontend/prompt-complexity.css")
style = style_path.read_text(encoding="utf-8")
old_mobile = '''@media (max-width: 520px) {
  .prompt-complexity-popover {
    width: min(300px, calc(100vw - 56px));
  }
}
'''
new_mobile = '''@media (max-width: 520px) {
  .prompt-complexity-popover {
    right: -4px;
    left: auto;
    width: min(290px, calc(100vw - 72px));
    overflow-wrap: anywhere;
  }

  .prompt-complexity-popover::before {
    right: 10px;
    left: auto;
  }
}
'''
if style.count(old_mobile) != 1:
    raise SystemExit("Unexpected mobile prompt complexity styles")
style_path.write_text(style.replace(old_mobile, new_mobile, 1), encoding="utf-8")

tests_path = Path("tests/test_static_assets.py")
tests = tests_path.read_text(encoding="utf-8")
if tests.count("prompt-complexity.css?v=2") != 1:
    raise SystemExit("Unexpected prompt complexity test reference")
tests = tests.replace("prompt-complexity.css?v=2", "prompt-complexity.css?v=3", 1)
anchor = '    assert ".prompt-complexity-popover" in complexity_style\n'
replacement = '''    assert ".prompt-complexity-popover" in complexity_style
    assert "right: -4px" in complexity_style
    assert "left: auto" in complexity_style
    assert "calc(100vw - 72px)" in complexity_style
'''
if tests.count(anchor) != 1:
    raise SystemExit("Unexpected prompt complexity test anchor")
tests_path.write_text(tests.replace(anchor, replacement, 1), encoding="utf-8")
