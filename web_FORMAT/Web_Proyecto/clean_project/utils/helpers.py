def build_keywords_expandidas(keywords_base):
    keywords_expandidas = []

    for k in keywords_base:
        kw = k.strip()
        keywords_expandidas.append(f"{kw}")

    return list(dict.fromkeys(keywords_expandidas))