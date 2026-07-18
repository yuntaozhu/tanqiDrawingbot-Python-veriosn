with open('src/routes.py') as f:
    for i, line in enumerate(f, 1):
        if 'def process_llm_interaction' in line:
            print(f"{i}: {line.strip()}")
