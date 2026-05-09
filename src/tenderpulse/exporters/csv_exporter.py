def export_csv(data, path):
    with open(path, 'w') as f:
        f.write(str(data))
