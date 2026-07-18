with open('src/routes.py') as f:
    for i, line in enumerate(f, 1):
        if 'def ' in line or '@router.' in line or '/api/' in line:
            if 'voice' in line.lower() or 'config' in line.lower() or 'setting' in line.lower():
                print(f"{i}: {line.strip()}")
