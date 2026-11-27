import requests
import time
from urllib.parse import quote

URL_BUSCA = "https://diariooficial.fortaleza.ce.gov.br/api/search"
WAIT = 6 #segundos; a fonte pede 5 (captcha-required -> intervalSeconds)
URL_PDF_FORTALEZA = "https://diariooficial.fortaleza.ce.gov.br/api/nodes/{id}/content?inline=1&name={nome}"


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
    entradas, total = buscar_mes_fortaleza(2026, 1)
    for entry in entradas:
        print(item_fortaleza(entry))