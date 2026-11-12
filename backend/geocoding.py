import hashlib

# Coordenadas reais de centróides dos bairros e regiões de Ribeirão Preto - SP
NEIGHBORHOOD_COORDINATES = {
    "centro": (-21.1775, -47.8103),
    "campos elísios": (-21.1620, -47.8010),
    "campos eliseos": (-21.1620, -47.8010),
    "ipiranga": (-21.1600, -47.8220),
    "alto do ipiranga": (-21.1650, -47.8280),
    "alto da boa vista": (-21.1960, -47.8180),
    "boulevard": (-21.1850, -47.8140),
    "vila tiberio": (-21.1730, -47.8250),
    "vila tibério": (-21.1730, -47.8250),
    "vila virgínia": (-21.1920, -47.8300),
    "vila virginia": (-21.1920, -47.8300),
    "vila seixas": (-21.1800, -47.8030),
    "vila amélia": (-21.1810, -47.8190),
    "vila carvalho": (-21.1650, -47.8120),
    "vila monte alegre": (-21.1680, -47.8450),
    "vila ana maria": (-21.1990, -47.7850),
    "jardim paulista": (-21.1740, -47.7880),
    "jardim botânico": (-21.2150, -47.8050),
    "jardim botanico": (-21.2150, -47.8050),
    "jardim califórnia": (-21.2050, -47.8150),
    "jardim california": (-21.2050, -47.8150),
    "jardim são luiz": (-21.2000, -47.8050),
    "jardim sao luiz": (-21.2000, -47.8050),
    "jardim sumaré": (-21.1890, -47.8090),
    "jardim sumare": (-21.1890, -47.8090),
    "jardim irajá": (-21.2030, -47.8000),
    "jardim iraja": (-21.2030, -47.8000),
    "jardim macedo": (-21.1780, -47.7820),
    "jardim palmas travassos": (-21.1860, -47.7780),
    "jardim palma travassos": (-21.1860, -47.7780),
    "jardim santa ângela": (-21.2060, -47.8100),
    "jardim santa angela": (-21.2060, -47.8100),
    "jardim zara": (-21.1600, -47.7700),
    "jardim antártica": (-21.1550, -47.8500),
    "jardim antartica": (-21.1550, -47.8500),
    "nova aliança": (-21.2180, -47.8270),
    "nova alianca": (-21.2180, -47.8270),
    "ribeirânia": (-21.1950, -47.7720),
    "ribeirania": (-21.1950, -47.7720),
    "lagoinha": (-21.1820, -47.7600),
    "bonfim paulista": (-21.2850, -47.8200),
    "vila do golfe": (-21.2350, -47.8350),
    "res. flórida": (-21.2250, -47.8100),
    "res. florida": (-21.2250, -47.8100),
    "parque industrial tanquinho": (-21.1400, -47.7950),
    "parque dos bandeirantes": (-21.1680, -47.7720),
    "parque ribeirão preto": (-21.2020, -47.8450),
    "simioni": (-21.1300, -47.8050),
    "adelino simioni": (-21.1300, -47.8050),
    "castelo branco": (-21.1700, -47.7650),
    "city ribeirão": (-21.2100, -47.7800),
    "city ribeirao": (-21.2100, -47.7800),
    "recreio das Acácias": (-21.2500, -47.7800),
    "iguatemi": (-21.2300, -47.8300),
    "ribeirão shopping": (-21.2180, -47.8270),
    "novo shopping": (-21.1850, -47.7650),
    "santa cruz": (-21.1980, -47.7950),
    "quintas de são josé": (-21.2400, -47.8100),
}

DEFAULT_RIBEIRAO_CENTER = (-21.1767, -47.8108)

def get_store_coordinates(neighborhood: str, store_name: str = "", address: str = "") -> tuple[float, float]:
    """
    Retorna (latitude, longitude) estimadas para a loja em Ribeirão Preto.
    Aplica uma dispersão determinística com base no nome/endereço para evitar que
    lojas no mesmo bairro fiquem exatamente sobrepostas no mesmo pixel do mapa.
    """
    clean_neighborhood = (neighborhood or "").lower().strip()
    
    # 1. Busca direta ou parcial no dicionário
    coords = None
    for k, v in NEIGHBORHOOD_COORDINATES.items():
        if k in clean_neighborhood or clean_neighborhood in k:
            coords = v
            break
            
    # 2. Se não encontrar, tenta pelo endereço
    if not coords and address:
        clean_addr = address.lower()
        for k, v in NEIGHBORHOOD_COORDINATES.items():
            if k in clean_addr:
                coords = v
                break

    # 3. Fallback para o Centro de Ribeirão Preto
    if not coords:
        coords = DEFAULT_RIBEIRAO_CENTER

    # 4. Jitter inteligente baseado no hash para espalhar os pins pela vizinhança
    seed_str = f"{store_name}_{address}_{clean_neighborhood}"
    h = int(hashlib.md5(seed_str.encode()).hexdigest()[:6], 16)
    
    # Offset de até ~250 metros
    offset_lat = ((h % 1000) - 500) * 0.000004
    offset_lng = (((h // 1000) % 1000) - 500) * 0.000004

    return (round(coords[0] + offset_lat, 6), round(coords[1] + offset_lng, 6))
