import urllib.request
import urllib.parse
import json

def discover_osm_stores():
    overpass_url = "https://overpass-api.de/api/interpreter"
    query = """
    [out:json][timeout:25];
    area["name"="Ribeirão Preto"]["admin_level"="8"]->.searchArea;
    (
      node["shop"]["website"](area.searchArea);
      way["shop"]["website"](area.searchArea);
    );
    out center;
    """
    
    data = urllib.parse.urlencode({'data': query}).encode('utf-8')
    req = urllib.request.Request(overpass_url, data=data, headers={'User-Agent': 'CompraRibeiraoBot/1.0'})
    
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            res = json.loads(resp.read().decode('utf-8'))
            elements = res.get('elements', [])
            print(f"OpenStreetMap encontrou {len(elements)} estabelecimentos comerciais com website em Ribeirão Preto!")
            valid_stores = []
            for el in elements:
                tags = el.get('tags', {})
                name = tags.get('name')
                website = tags.get('website')
                shop_type = tags.get('shop')
                phone = tags.get('phone') or tags.get('contact:phone') or tags.get('contact:whatsapp')
                street = tags.get('addr:street')
                suburb = tags.get('addr:suburb')
                
                if name and website:
                    valid_stores.append({
                        "name": name,
                        "website": website,
                        "type": shop_type,
                        "phone": phone,
                        "neighborhood": suburb
                    })
            return valid_stores
    except Exception as e:
        print(f"Erro na consulta Overpass: {e}")
        return []

if __name__ == "__main__":
    stores = discover_osm_stores()
    for s in stores[:15]:
        print(f"• {s['name']} | {s['type']} | {s['website']} | Bairro: {s['neighborhood']}")
