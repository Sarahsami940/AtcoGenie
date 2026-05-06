$file = "AtcoGenie.Server\wwwroot\theme-init.js"
$lines = Get-Content $file

$newBlock = @(
  "  /* -- Hide theme toggle button -- */",
  "  function hideThemeToggle() {",
  "    document.querySelectorAll('button').forEach(btn => {",
  "      const label = (btn.getAttribute('aria-label') || btn.getAttribute('title') || '').toLowerCase();",
  "      if (/dark|light|theme|mode/.test(label)) { btn.style.setProperty('display','none','important'); return; }",
  "      const svgText = btn.querySelector('svg')?.innerHTML || '';",
  "      if (/moon|sun|brightness/i.test(svgText)) { btn.style.setProperty('display','none','important'); }",
  "    });",
  "  }",
  "",
  "  /* -- Hide file chips from the input bar -- */",
  "  function hideInputChips() {",
  "    document.querySelectorAll('textarea').forEach(ta => {",
  "      const parent = ta.parentElement;",
  "      if (!parent) return;",
  "      Array.from(parent.children).forEach(child => {",
  "        if (child === ta || child.contains(ta)) return;",
  "        if (child.tagName === 'TEXTAREA' || child.tagName === 'BUTTON') return;",
  "        if (child.offsetWidth > 400 || child.offsetHeight > 200) return;",
  "        const hasCloseBtn = !!child.querySelector('button');",
  "        const txt = child.textContent?.trim() || '';",
  "        if (!hasCloseBtn || txt.length < 3 || txt.length > 100) return;",
  "        child.style.setProperty('display','none','important');",
  "      });",
  "    });",
  "  }"
)

# 0-indexed: lines 544 to 586 (inclusive) = lines 545-587 in 1-indexed
$before = $lines[0..543]
$after  = $lines[587..($lines.Length - 1)]
$result = $before + $newBlock + $after

Set-Content $file $result -Encoding UTF8
Write-Host "Done. Total lines: $($result.Length)"
