# Antigravity Agent Rules for this Project

**1. CRITICAL RULE: PROACTIVE LOGGING**
Before you execute any tool to create, modify, or delete a code file, you MUST FIRST append a detailed log entry with the current timestamp to the `dailyupdates.md` file located in the project root. This log must describe exactly what you are about to implement and which files you are about to modify. Do not make any code changes until the `dailyupdates.md` file has been successfully updated.
- *Format:* Use markdown, group entries by current date, and ensure timestamps reflect local time.

**2. CRITICAL RULE: TASK COMPLEXITY & MODEL ROUTING**
When the user provides a new task, you must first analyze its complexity before taking action.
- **Simple Task:** (e.g., UI tweaks, typo fixes, simple console logs). Recommendation: Fast/Lightweight model.
- **Normal Task:** (e.g., standard API endpoints, standalone functions). Recommendation: Balanced/Standard model.
- **Complex Task:** (e.g., cross-file refactoring, new architecture, difficult debugging). Recommendation: Most capable model (e.g., Gemini Pro).

*Workflow Steps:*
1. Output a brief message stating the complexity level.
2. Explicitly recommend whether the user should stay on their current model or switch.
3. Explain your exact understanding of the task and what you intend to do.
4. STOP and WAIT for the user to explicitly confirm your understanding before taking ANY further action (including logging or coding).

**3. CRITICAL RULE: MANDATORY PLANNING FOR COMPLEX TASKS**
If a task is deemed **Complex**, you must automatically trigger a "Planning Phase". Before writing any code, you must create an `implementation_plan.md` artifact detailing the proposed architecture or code changes. You must wait for the user to explicitly approve this plan before proceeding to code execution.
