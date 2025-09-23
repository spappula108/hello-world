## Pharma QA/QC Workflow App (Dash)

This is a modular prototype for a pharmaceutical Quality Assurance workflow with role-based access, audit logging, automated decisioning, and a RAG-powered SOP assistant.

### Features
- Request initiation with unique Sample ID generation
- QC reception and analysis assignment
- Analysis entry with validations and optional file uploads
- Automated Pass/Fail decision against specifications with rationale
- Audit logging and e-signature for approvals
- Historical reporting downloads (CSV)
- Role-based login (Requester, QC, QA, Admin)
- "Ask SOP" sidebar using TF-IDF retrieval and optional local LLM via Ollama

### Tech
- Dash UI (lightweight dependencies)
- SQLite storage (file-based)
- Data prototypes in JSON

### Setup
1. Python 3.10+
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the app:
   ```bash
   python3 app.py
   ```

The app will initialize the SQLite database on first run and seed example users, specs, and SOP corpus.

### Default Roles and Demo Users (seeded on first run)
- requester / requester123
- qc / qc123
- qa / qa123
- admin / admin123

### Optional: Local LLM via Ollama
- Install Ollama and pull a model (e.g., `mistral`, `llama2`, `openhermes`)
- Set environment variable `OLLAMA_MODEL` (defaults to `mistral`)
- Start Ollama server (default `http://localhost:11434`)

### Security & Compliance Notes (High-Level)
- Use strong password hashing (bcrypt) and role-based authorization
- Record immutable audit logs for all critical actions; include e-signatures
- Separate duties: Requesters, QC, QA, Admin
- Validate and sanitize all user inputs; restrict file types for uploads
- SOP/specs under change control; version and reference in records
- Time synchronization (NTP) and unique Sample IDs
- Regular backups and secure DB access; secrets not in source control

See the in-app "Security & Best Practices" page for more details.
# hello-world
First foray in Github
What's up, dude? Cutout choosi asalu manishini marachi poku
