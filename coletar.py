import requests

URL_BUSCA = "https://diariooficial.fortaleza.ce.gov.br/api/search"

payload = {"ano": "2026", "mes": "11", "nrDom": None, "conteudo": None, "captcha": "", "page": 1, "pageSize": 30}

resposta = requests.post(URL_BUSCA, json=payload, timeout=30)
resposta.raise_for_status()
dados = resposta.json()

print(dados["list"]["pagination"])
for item in dados["list"]["entries"]:
    e = item["entry"]
    print(e["nrDiarioOficial"], e["dataPublicacao"], e["name"])