"""Canonical snapshot mapping. Preserve nested packing data and raw input independently."""
from copy import deepcopy
from routing_guides.evaluator import number

MAPPING_VERSION = 'shiphero-1.0'


def normalize(raw: dict, overrides: dict | None = None) -> tuple[dict, list[str]]:
    if not isinstance(raw, dict):
        raise ValueError('Scenario must be a JSON object.')
    warnings = []
    if raw.get('schema_version') == '1.0' and 'shipment' in raw:
        normalized = deepcopy(raw)
    else:
        envelope = raw.get('data', raw)
        order = envelope.get('wholesale_order', envelope)
        if isinstance(order, dict) and isinstance(order.get('data'), dict):
            order = order['data']
        if not isinstance(order, dict):
            raise ValueError('Expected a wholesale order object.')
        layout = order.get('packing_layout')
        destination = raw.get('destination') or order.get('destination') or order.get('shipping_address') or (order.get('order') or {}).get('shipping_address')
        shipment = {k: order[k] for k in ('id', 'customer_po_number', 'store_location_number', 'department', 'shipping_option', 'trading_partner_id', 'wholesale_shipping_details', 'distribution_center', 'distribution_center_number') if k in order}
        if destination is not None:
            shipment['destination'] = deepcopy(destination)
        normalized = {'schema_version': '1.0', 'shipment': shipment, 'packing_layout': deepcopy(layout)}
        if isinstance(layout, dict) and isinstance(layout.get('containers'), list):
            cartons, pallets, items = [], [], []
            def visit(container, path, parent_id=None):
                if not isinstance(container, dict):
                    raise ValueError('Every packing container must be an object.')
                details = container.get('details') or {}
                item = {**deepcopy(container), 'id': path, 'parent_id': parent_id}
                if details.get('weight_in_oz') is not None:
                    item['weight'] = {'value': str(number(details['weight_in_oz'])), 'unit': 'oz'}
                for dim in ('height', 'width', 'length'):
                    if details.get(dim) is not None:
                        item[dim] = {'value': str(number(details[dim])), 'unit': 'in'}
                kind = container.get('type')
                if kind in ('Pallet', 'UOM Pallet'):
                    pallets.append(item)
                elif kind in ('Box', 'Package', 'CasePack'):
                    cartons.append(item)
                else:
                    warnings.append(f'Unrecognized container type at {path}; physical coverage requires review.')
                for index, line in enumerate(container.get('line_items') or []):
                    items.append({**deepcopy(line), 'id': f'{path}/item/{index}', 'parent_id': path})
                if kind in ('CasePack', 'UOM Pallet'):
                    warnings.append(f'{path}: quantity represents cases; no each-level total or aggregate weight is inferred.')
                for index, child in enumerate(container.get('containers') or []):
                    visit(child, f'{path}/{index}', path)
            for index, container in enumerate(layout['containers']):
                visit(container, f'container/{index}')
            normalized.update(cartons=cartons, pallets=pallets, items=items)
        else:
            warnings.append('Packing layout unavailable. Container checks will be Cannot determine.')
        if destination is None:
            warnings.append('Destination unavailable; no store or DC destination is inferred.')
    if overrides:
        # Explicit shallow top-level replacement: no concealed merge or accidental double counting.
        forbidden = set(overrides) - {'shipment', 'cartons', 'pallets', 'items', 'evidence'}
        if forbidden:
            raise ValueError('Overrides may replace shipment, cartons, pallets, items or evidence only.')
        normalized.update(deepcopy(overrides))
        warnings.append('User overrides replace the named top-level fields; raw input remains unchanged.')
    if not isinstance(normalized.get('shipment'), dict):
        raise ValueError('shipment must be an object.')
    for key in ('cartons', 'pallets', 'items'):
        if key in normalized and (not isinstance(normalized[key], list) or any(not isinstance(x, dict) for x in normalized[key])):
            raise ValueError(f'{key} must be an array of objects.')
    if 'evidence' in normalized and not isinstance(normalized['evidence'], dict):
        raise ValueError('evidence must be an object.')
    return normalized, warnings
