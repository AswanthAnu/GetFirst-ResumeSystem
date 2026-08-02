"""
Update get_modified_outputs to use template.tex
"""

with open('tools/llm_handler.py', encoding='utf-8') as f:
    content = f.read()

old_start = content.find('def get_modified_outputs')
if old_start == -1:
    print('ERROR: Could not find function')
    exit(1)

new_function = '''def get_modified_outputs(
    history_text: str,
    reference_cv_text: str,
    job_description: str,
) -> dict[str, Any]:
    """
    LLM Call: Generate a NEW tailored LaTeX CV + cover letter from career history.

    Args:
        history_text: Plain text from the candidate's complete career history (my_history.docx).
        reference_cv_text: Plain text extracted from the uploaded PDF CV (defines style/structure).
        job_description: Raw job description text.

    Returns:
        Parsed dict with 'modified_cv_latex', 'cover_letter_text', 'key_changes_summary'.

    Raises:
        LLMError: If the API call fails.
    """
    # Use template.tex for the EXACT LaTeX style
    from pathlib import Path
    template_path = Path(__file__).parent.parent / "template.tex"
    if template_path.exists():
        template_text = template_path.read_text(encoding="utf-8")
    else:
        # Fallback: use the reference CV text (plain text from uploaded PDF)
        template_text = reference_cv_text

    system_prompt = SYSTEM_PROMPT_CALL_2.format(
        template=template_text,
        schema=OUTPUT_SCHEMA,
    )
    user_prompt = USER_PROMPT_CALL_2.format(
        history_text=history_text,
        reference_cv_text=reference_cv_text,
        job_description=job_description,
    )

    return _call_api(system_prompt, user_prompt, temperature=0.2)
'''

new_content = content[:old_start] + new_function

with open('tools/llm_handler.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print('Successfully updated get_modified_outputs to use template.tex')
print('File size:', len(new_content), 'chars')