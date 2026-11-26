import requests
import time
from urllib.parse import quote

URL_BUSCA = "https://diariooficial.fortaleza.ce.gov.br/api/search"
WAIT = 6 #segundos; a fonte pede 5 (captcha-required -> intervalSeconds)

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

entradas, total = buscar_mes_fortaleza(2026, 4)
print(len(entradas), total)

'''
print(dados["list"]["pagination"])
for item in dados["list"]["entries"]:
    e = item["entry"]
    print(e["nrDiarioOficial"], e["dataPublicacao"], e["name"])
'''