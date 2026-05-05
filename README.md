# 📄 AI Resume Tailor (LaTeX + LLM Controlled)

A deterministic system to tailor your CV for each job application without rewriting everything manually — and without hallucinating experience.

---

## 🚀 Problem

Applying to jobs usually looks like:

- Find a role  
- Tweak your CV  
- Tweak it again  
- Write a cover letter  
- Forget what you even sent  

After a few applications, you lose track of:
- what version of your CV you used  
- what you emphasized  
- how you positioned yourself  

---

## 💡 Solution

This tool automates the process while keeping everything **truthful, structured, and trackable**.

### Flow:

1. Paste a **job description**
2. Upload your **LaTeX CV**
3. Generate:
   - Tailored CV (LaTeX-safe)
   - Matching cover letter (DOCX)
4. Review → Confirm → Save

---

## ✨ Features

### 🎯 Smart CV Alignment
- Rewrites CV to match job requirements  
- Emphasizes relevant experience  
- Reorders content for better alignment  

### 🔒 No Hallucination
- Does **NOT** add fake experience  
- Only:
  - Rephrases  
  - Emphasizes  
  - Restructures existing content  

### 🧠 Explainable Changes
- Shows:
  - What changed  
  - What was emphasized  
  - What gaps exist for the role  

### 📂 Application Memory System
- Stores each application with:
  - Job description  
  - Tailored CV version  
  - Cover letter  
  - Timestamp  

👉 So when a recruiter calls, you know exactly what you sent.

---

## 🏗️ Architecture

Built using **Antigravity Framework**

### B.L.A.S.T Protocol:
- **Blueprint** → Define schema + rules  
- **Link** → Validate APIs  
- **Architect** → 3-layer system  
- **Stylize** → Output formatting  
- **Trigger** → Execution flow  

### A.N.T Layers:

#### 1. Architecture (`/architecture`)
- SOPs
- Logic definitions
- Constraints (no hallucination)

#### 2. Navigation
- Controls flow
- Routes data between LLM and tools

#### 3. Tools (`/tools`)
- Deterministic Python scripts:
  - CV parser
  - LLM handler
  - Validation engine
  - DOCX generator
  - Storage layer

---

## ⚙️ Tech Stack

- **LLM:** DeepSeek v4 Pro  
- **Framework:** Antigravity (B.L.A.S.T + A.N.T)  
- **CV Format:** LaTeX  
- **Backend:** Python  
- **Storage:** Local DB / File-based  
- **Document Generation:** python-docx  

---

## 📊 System Design

### Input:
- Job description (text)
- CV (LaTeX)

### Output:
- Modified CV (LaTeX)
- Cover letter (DOCX)
- Change summary + gap analysis

---

## 🔐 Guardrails

To prevent unreliable outputs:

- ❌ No new companies / roles  
- ❌ No fake skills or tools  
- ❌ No fabricated achievements  

- ✅ Only edits existing content  
- ✅ Strict schema-based generation  
- ✅ Validation layer checks differences  

---

## 🔁 Regeneration Logic

- Each generation is **stateless**
- No memory of previous outputs
- Ensures clean, independent results every time

---


---

## 🧪 Example Use Case

> Apply for a Backend Engineer role

- Paste job description  
- Upload base CV  
- Generate tailored version  
- Review changes + gaps  
- Export CV + cover letter  
- Save record  

Later:
> Recruiter calls → open app → see exact version sent

---

## 📌 Status

Personal tool — not production-ready (yet).

Built to:
- reduce repetitive work  
- maintain consistency  
- improve awareness of CV positioning  

---

## 🤝 Why This Exists

Most AI resume tools:
- rewrite everything blindly  
- hallucinate experience  
- lose structure  

This system focuses on:
> **controlled transformation, not generation**

---

## 📬 Feedback

If you’ve ever:
- customized your CV 20 times  
- forgotten what you sent  
- struggled to align with job descriptions  

Would love to hear your thoughts.

---
