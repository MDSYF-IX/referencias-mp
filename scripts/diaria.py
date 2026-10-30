"""Actualización diaria desde la API de Mercado Público (requiere el secreto MP_TICKET).

1. licitaciones.json?fecha=<ayer>&estado=adjudicada  (una consulta, nacional)
2. Prefiltro por el tipo del sufijo del código (LR, I2, O1, O2) y por palabras de no-obra.
3. Detalle de cada una (una consulta por licitación); se queda con las de las regiones de
   config/filtros.json que cumplen el filtro de obras.
4. Agrega o reemplaza (clave: código) en el archivo del año y actualiza indice.json.

Sin MP_TICKET no hace nada: la carga sigue saliendo de los datos abiertos (carga.py).
Campos verificados con una respuesta real (30-10-2026). «fecha» con estado=adjudicada es la
fecha de adjudicación (Fechas.FechaAdjudicacion). Ver una respuesta: --muestra CODIGO.

Uso: python scripts/diaria.py --publico public [--fecha DDMMAAAA]
"""
import argparse, datetime, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comun import FILTROS, norm, region_slug, tipo_de_codigo, es_obra, num, get_json, cargar_uf, completar, leer_region, escribir_region, escribir_indice, rellenar_uf, _tiene

BASE = 'https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json'
LIMITE = 9000


class Contador:
    n = 0

    @classmethod
    def get(cls, url):
        if cls.n >= LIMITE:
            raise RuntimeError(f'Se alcanzó el límite interno de {LIMITE} consultas')
        cls.n += 1
        return get_json(url)


def fecha_iso(s):
    return str(s or '')[:10] or None


def desde_detalle(d):
    """Licitación de la API → mismos campos que carga.py (sin los calculados)."""
    comp, fechas = d.get('Comprador') or {}, d.get('Fechas') or {}
    adj, prov = 0.0, {}
    for it in ((d.get('Items') or {}).get('Listado') or []):
        a = it.get('Adjudicacion') or {}
        if a.get('RutProveedor'):
            adj += num(a.get('Cantidad')) * num(a.get('MontoUnitario'))
            prov[a['RutProveedor']] = a.get('NombreProveedor') or ''
    return dict(
        cod=d['CodigoExterno'], nom=(d.get('Nombre') or '').strip(), org=(comp.get('NombreOrganismo') or '').strip(),
        reg=region_slug(comp.get('RegionUnidad')), com=(comp.get('ComunaUnidad') or '').strip(),
        tipo=d.get('Tipo') or tipo_de_codigo(d['CodigoExterno']), fpub=fecha_iso(fechas.get('FechaPublicacion')),
        fadj=fecha_iso(fechas.get('FechaAdjudicacion')), mon=d.get('Moneda') or 'CLP', est=num(d.get('MontoEstimado')) or None,
        adj=round(adj, 2), ofe=int(num((d.get('Adjudicacion') or {}).get('NumeroOferentes'))) or None,
        prov=[f'{n} ({r})' for r, n in prov.items()], desc=d.get('Descripcion') or '', obras=d.get('Obras'),
        bip=str(d['CodigoBIP']).strip() if d.get('CodigoBIP') else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--publico', required=True)
    ap.add_argument('--fecha', help='DDMMAAAA; por defecto, ayer')
    ap.add_argument('--muestra', help='imprime la respuesta cruda del detalle de un código y termina')
    a = ap.parse_args()
    ticket = os.environ.get('MP_TICKET')
    if not ticket:
        print('Sin MP_TICKET: se omite la actualización diaria por API.')
        return
    if a.muestra:
        print(json.dumps(Contador.get(f'{BASE}?codigo={a.muestra}&ticket={ticket}'), ensure_ascii=False, indent=1)[:6000])
        return
    fecha = a.fecha or (datetime.date.today() - datetime.timedelta(days=1)).strftime('%d%m%Y')
    lista = Contador.get(f'{BASE}?fecha={fecha}&estado=adjudicada&ticket={ticket}').get('Listado') or []
    pre = [x for x in lista if tipo_de_codigo(x.get('CodigoExterno')) in FILTROS['tipos']
           and not _tiene(FILTROS['palabras_no_obras'], norm(x.get('Nombre')))]
    nuevas, descartadas, errores = {}, 0, []
    for x in pre:
        try:
            det = (Contador.get(f"{BASE}?codigo={x['CodigoExterno']}&ticket={ticket}").get('Listado') or [None])[0]
        except Exception as e:
            errores.append(f"{x['CodigoExterno']}: {e}"); continue
        if not det:
            continue
        L = desde_detalle(det)
        if L['reg'] in FILTROS['regiones'] and es_obra(L['tipo'], L['nom'], L.pop('obras')):
            nuevas[L['cod']] = L
        else:
            descartadas += 1
    if nuevas:
        uf = cargar_uf(a.publico, {int((L['fadj'] or L['fpub'])[:4]) for L in nuevas.values()})
        for reg in FILTROS['regiones']:
            actual = leer_region(a.publico, reg)
            for c, L in nuevas.items():
                if L['reg'] == reg:
                    actual[c] = completar(L, uf)
            rellenar_uf(actual, uf)
            escribir_region(a.publico, reg, actual)
        escribir_indice(a.publico)
    print(f'Fecha {fecha}: {len(lista)} adjudicadas en el país, {len(pre)} pasan el prefiltro, '
          f'{len(nuevas)} nuevas o actualizadas, {descartadas} descartadas, {len(errores)} errores, {Contador.n} consultas.')
    for e in errores:
        print('  ERROR', e)


if __name__ == '__main__':
    main()
