import requests
import time
import hashlib
import pymupdf
from urllib.parse import quote
from pathlib import Path

URL_BUSCA = "https://diariooficial.fortaleza.ce.gov.br/api/search"
WAIT = 6 #segundos; a fonte pede 5 (captcha-required -> intervalSeconds)
URL_PDF_FORTALEZA = "https://diariooficial.fortaleza.ce.gov.br/api/nodes/{id}/content?inline=1&name={nome}"
PASTA_PDF = Path("pdfs")


def tipo_fortaleza(nr):
    nr = nr.replace(" ", "").lower()
    if nr.endswith("s") and nr[:-1].isdigit():
        return "suplemento", nr[:-1]
    if nr.isdigit():
        return "normal", nr
    return None, nr


def item_fortaleza(entry):
    tipo, numero = tipo_fortaleza(entry["nrDiarioOficial"])
    return {
        "fonte": "fortaleza",
        "data_publicacao": entry["dataPublicacao"][:10],
        "numero": numero,
        "tipo": tipo,
        "url": URL_PDF_FORTALEZA.format(id=entry["id"], nome=quote(entry["name"])),
        "titulo_fonte": entry["name"],
    }


def baixar_pdf(url):
    nome = hashlib.sha256(url.encode()).hexdigest()[:16] + ".pdf"
    caminho = PASTA_PDF / nome
    if not caminho.exists():
        resposta = requests.get(url, timeout=60)
        resposta.raise_for_status()
        if not resposta.content.startswith(b"%PDF"):
            raise ValueError(f"A resposta não é um PDF: {url}")
        PASTA_PDF.mkdir(exist_ok=True)
        caminho.write_bytes(resposta.content)
        time.sleep(WAIT)
    conteudo = caminho.read_bytes()
    return caminho, hashlib.sha256(conteudo).hexdigest()


def extrair_texto(caminho):
    with pymupdf.open(caminho) as doc:
        paginas = [pagina.get_text() for pagina in doc]
    return "\f".join(paginas), len(paginas)


def buscar_mes_fortaleza(ano, mes):
    entradas = []
    pagina = 1
    while True:  
        payload = {"ano": str(ano), "mes": f"{mes:02d}", "nrDom": None, "conteudo": None, "captcha": "", "page": pagina, "pageSize": 30}
        resposta = requests.post(URL_BUSCA, json=payload, timeout=30)
        resposta.raise_for_status()
        lista = resposta.json()["list"]
        entradas += [item["entry"] for item in lista["entries"]]
        time.sleep(WAIT)
        if not lista["pagination"]["hasMoreItems"]:
            return entradas, lista["pagination"]["totalItems"]
        pagina += 1

if __name__ == "__main__":
    for caminho in PASTA_PDF.glob("*.pdf"):
        texto, paginas = extrair_texto(caminho)
        por_pagina = [len(p) for p in texto.split("\f")]
        print(caminho.name, paginas, "páginas | caracteres por página:", por_pagina)
        print(texto[:300])
        print("-" * 60)