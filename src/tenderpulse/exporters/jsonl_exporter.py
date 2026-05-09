def export_jsonl(data, path):
    with open(path, 'w') as f:
        for line in data:
            f.write(f"{line}\n")
