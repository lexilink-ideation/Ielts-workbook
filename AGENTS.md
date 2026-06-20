## Imported Claude Cowork project instructions

## IELTS Workbook Generator

### One-time setup
```bash
pip install anthropic pdfplumber
export ANTHROPIC_API_KEY=sk-ant-...   # add to ~/.zshrc to persist
```

### Workflow
1. Drop a source file into `input/` — any of:
   - A vocabulary list (`.txt`)
   - A reading passage (`.txt` or `.pdf`)
   - A listening script (`.txt`)
2. Run the generator:
   ```bash
   cd "IELTS Vocabulary workbook"
   python3 generate_workbook.py
   ```
3. Open the generated HTML in your browser to review
4. Update `index.html` to mark the new unit pair as available
5. `git add . && git commit -m "Add Units X-Y: Topic A · Topic B" && git push`

### Optional flags
```
--units 11-12          override unit numbers (default: auto-detect)
--level 3              1=Beginner  2=Foundation  3=Academic
--model claude-sonnet-4-6   faster/cheaper model
```

### Asking Claude in Cowork instead
Tell Claude: "Generate units 9–10 from the file in input/"
Claude will read the file and generate the HTML directly without running the script.
