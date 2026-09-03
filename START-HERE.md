# How to start the app

You need **two terminals** open at the same time. One runs the brain
(backend), one runs the screen (frontend). Both must stay open the whole time.

In VS Code or Antigravity: **Terminal → New Terminal**. To get the second one,
click the **+** button in the terminal panel.

---

## Terminal 1 - the backend

Type this and press Enter:

```powershell
cd backend; .venv\Scripts\python -m uvicorn app.main:app --port 8000
```

**Wait.** When you see this, it worked:

```
Application startup complete.
Uvicorn running on http://127.0.0.1:8000
```

Now **leave this terminal alone.** Don't type in it, don't close it.

---

## Terminal 2 - the frontend

Click **+** to open a second terminal, then type:

```powershell
cd frontend; npm run dev
```

When you see this, it worked:

```
VITE ready in 400 ms
Local: http://localhost:5173/
```

Leave this one alone too.

---

## Open the app

Go to your browser and visit:

**http://localhost:5173**

Sign in with:

- Email: **demo4@example.com**
- Password: **correct-horse-battery**

That's it. Ask a question.

---

## Stopping it

Click on a terminal and press **Ctrl + C**. Do that in both.

---

## When something goes wrong

### "The token '&&' is not a valid statement separator"

You typed `&&`. This terminal wants a semicolon `;` instead. Use the commands
above exactly as written.

### "Port 8000 is already in use"

An old backend is still running from last time. Kill it:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

Then start Terminal 1 again.

### The page won't load

Use **localhost**, not `127.0.0.1`, in the browser. The frontend only answers
to `localhost`. (The backend is the opposite - but you never type that one
into a browser, so it doesn't matter.)

### Something looks broken or empty

Open a **third** terminal and run:

```powershell
cd backend; .venv\Scripts\python -m scripts.reset_demo_state
```

This rebuilds the demo account, the database connection, the glossary word,
the saved correction and the dashboard. Then refresh the browser page.

### "Is the AI actually working?"

```powershell
cd backend; .venv\Scripts\python -m scripts.check_llm
```

If it ends with **"a real model translated the question"**, everything is
working. If it says *placeholder*, the AI key stopped working - the rest of
the app still runs fine.

---

## The very first time only

If `npm run dev` complains that something is missing, install the packages
once:

```powershell
cd frontend; npm install
```

You should not need to do this again.

---

## Before you present: one command

```powershell
cd backend; .venv\Scripts\python -m scripts.preflight
```

It checks the interpreter, the provider keys and SDKs, and opens every
connection for real - then asks each demo question once so the answers are
cached. After that the same questions come back in under a tenth of a second
without calling the model at all, so a rate limit or a dropped network cannot
derail the demo.

It ends with **READY** when everything is in order, and names what is wrong
when it is not.
