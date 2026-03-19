#!/usr/bin/env bash
# Create demo repos for testing DeepRoute + meta-prompt integration.
# Each repo represents a different use case.
set -euo pipefail

DEMO_DIR="/tmp/demo-workspace"
rm -rf "$DEMO_DIR"
mkdir -p "$DEMO_DIR"

echo "=== Creating demo repos ==="

# --- 1. Python API project ---
API_DIR="$DEMO_DIR/notes-api"
mkdir -p "$API_DIR/src/routes" "$API_DIR/src/models" "$API_DIR/tests"

cat > "$API_DIR/src/main.py" << 'PYEOF'
from fastapi import FastAPI
from src.routes.notes import router as notes_router
from src.routes.tags import router as tags_router

app = FastAPI(title="Notes API", version="0.1.0")
app.include_router(notes_router, prefix="/notes")
app.include_router(tags_router, prefix="/tags")

@app.get("/health")
async def health():
    return {"status": "ok"}
PYEOF

cat > "$API_DIR/src/routes/__init__.py" << 'PYEOF'
PYEOF
cat > "$API_DIR/src/routes/notes.py" << 'PYEOF'
from fastapi import APIRouter, HTTPException
from src.models.schemas import Note, NoteCreate

router = APIRouter()
_notes: dict[int, Note] = {}
_next_id = 1

@router.get("/")
async def list_notes(tag: str | None = None):
    notes = list(_notes.values())
    if tag:
        notes = [n for n in notes if tag in n.tags]
    return notes

@router.post("/", status_code=201)
async def create_note(note: NoteCreate):
    global _next_id
    new = Note(id=_next_id, **note.model_dump())
    _notes[_next_id] = new
    _next_id += 1
    return new

@router.get("/{note_id}")
async def get_note(note_id: int):
    if note_id not in _notes:
        raise HTTPException(404, "Note not found")
    return _notes[note_id]
PYEOF

cat > "$API_DIR/src/routes/tags.py" << 'PYEOF'
from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def list_tags():
    return ["work", "personal", "ideas", "todo"]
PYEOF

cat > "$API_DIR/src/models/__init__.py" << 'PYEOF'
PYEOF
cat > "$API_DIR/src/models/schemas.py" << 'PYEOF'
from pydantic import BaseModel

class NoteCreate(BaseModel):
    title: str
    content: str
    tags: list[str] = []

class Note(NoteCreate):
    id: int
PYEOF

cat > "$API_DIR/src/__init__.py" << 'PYEOF'
PYEOF

cat > "$API_DIR/tests/__init__.py" << 'PYEOF'
PYEOF
cat > "$API_DIR/tests/test_notes.py" << 'PYEOF'
def test_create_note():
    assert True

def test_list_notes():
    assert True
PYEOF

cat > "$API_DIR/pyproject.toml" << 'PYEOF'
[project]
name = "notes-api"
version = "0.1.0"
dependencies = ["fastapi", "uvicorn", "pydantic"]
PYEOF

cat > "$API_DIR/README.md" << 'PYEOF'
# Notes API
REST API for note-taking with tagging support. Built with FastAPI.
PYEOF

cat > "$API_DIR/Dockerfile" << 'PYEOF'
FROM python:3.12-slim
WORKDIR /app
COPY . .
CMD ["uvicorn", "src.main:app"]
PYEOF

cd "$API_DIR" && git init && git add . && git commit -m "initial notes-api"
echo "  Created: $API_DIR"


# --- 2. Writing/journal project (non-code) ---
JOURNAL_DIR="$DEMO_DIR/daily-journal"
mkdir -p "$JOURNAL_DIR/entries/2026" "$JOURNAL_DIR/templates" "$JOURNAL_DIR/tags"

cat > "$JOURNAL_DIR/README.md" << 'EOF'
# Daily Journal

Personal journal with markdown entries, templates, and tag-based organization.

## Structure
- `entries/YYYY/MM-DD.md` — daily entries
- `templates/` — entry templates
- `tags/` — tag indexes
EOF

cat > "$JOURNAL_DIR/templates/daily.md" << 'EOF'
# {{date}}

## Morning
- Mood:
- Goals:

## Notes

## Evening Reflection
- What went well:
- What to improve:
EOF

cat > "$JOURNAL_DIR/templates/weekly-review.md" << 'EOF'
# Week of {{date}}

## Highlights

## Challenges

## Next Week Goals
EOF

cat > "$JOURNAL_DIR/entries/2026/03-17.md" << 'EOF'
# March 17, 2026

## Morning
- Mood: focused
- Goals: ship the deeproute MCP server

## Notes
Working on multi-layer markdown routing. The key insight is progressive disclosure —
ROUTER.md as the index, layer files for depth, source code only when needed.

## Evening Reflection
- What went well: got the scanner and generator working
- What to improve: need better change classification in updater
EOF

cat > "$JOURNAL_DIR/entries/2026/03-18.md" << 'EOF'
# March 18, 2026

## Morning
- Mood: productive
- Goals: integration tests, skill installer

## Notes
Testing the full pipeline: scan → analyze → generate → update. All 8 MCP tools
verified. The LangGraph backend works but direct Anthropic calls are simpler and
more reliable for this use case.

## Evening Reflection
- What went well: 8/8 integration tests passing
- What to improve: should add Docker test harness for clean-slate validation
EOF

cat > "$JOURNAL_DIR/tags/deeproute.md" << 'EOF'
# #deeproute

Entries mentioning DeepRoute development:
- [2026-03-17](../entries/2026/03-17.md)
- [2026-03-18](../entries/2026/03-18.md)
EOF

cd "$JOURNAL_DIR" && git init && git add . && git commit -m "initial journal"
echo "  Created: $JOURNAL_DIR"


# --- 3. Multi-service project ---
FRONTEND_DIR="$DEMO_DIR/webapp-frontend"
mkdir -p "$FRONTEND_DIR/src/components" "$FRONTEND_DIR/src/pages" "$FRONTEND_DIR/public"

cat > "$FRONTEND_DIR/package.json" << 'EOF'
{
  "name": "webapp-frontend",
  "version": "0.1.0",
  "dependencies": {
    "next": "^15.0.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  }
}
EOF

cat > "$FRONTEND_DIR/tsconfig.json" << 'EOF'
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "strict": true,
    "jsx": "preserve",
    "moduleResolution": "bundler"
  }
}
EOF

cat > "$FRONTEND_DIR/src/pages/index.tsx" << 'EOF'
import { NoteList } from "../components/NoteList";

export default function Home() {
  return (
    <main>
      <h1>Notes</h1>
      <NoteList />
    </main>
  );
}
EOF

cat > "$FRONTEND_DIR/src/components/NoteList.tsx" << 'EOF'
"use client";
import { useEffect, useState } from "react";

interface Note {
  id: number;
  title: string;
  content: string;
  tags: string[];
}

export function NoteList() {
  const [notes, setNotes] = useState<Note[]>([]);

  useEffect(() => {
    fetch("/api/notes").then(r => r.json()).then(setNotes);
  }, []);

  return (
    <ul>
      {notes.map(n => (
        <li key={n.id}>{n.title} — {n.tags.join(", ")}</li>
      ))}
    </ul>
  );
}
EOF

cat > "$FRONTEND_DIR/README.md" << 'EOF'
# Webapp Frontend
Next.js frontend for the Notes API. Displays and manages notes.
EOF

cd "$FRONTEND_DIR" && git init && git add . && git commit -m "initial frontend"
echo "  Created: $FRONTEND_DIR"

echo ""
echo "=== Demo workspace ready at $DEMO_DIR ==="
echo "Repos: notes-api, daily-journal, webapp-frontend"
