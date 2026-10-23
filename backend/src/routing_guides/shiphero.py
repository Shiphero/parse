"""Read-only ShipHero query. No mutations and no order data sent to AI providers."""
import httpx
from routing_guides.connections import connection

QUERY = '''query RoutingGuideScenario($id: String!) {
  wholesale_order(id: $id) {
    data {
      id status shipping_option customer_po_number store_location_number department trading_partner_id
      distribution_center distribution_center_number packing_layout
      order { account_id shipping_address { city state zip country } }
    }
  }
}'''


async def fetch_order(order_id: str) -> dict:
    key = (await connection('shiphero'))['key']
    if not key:
        raise ValueError('Add a ShipHero access token in Connections.')
    try:
        async with httpx.AsyncClient(timeout=40) as client:
            response = await client.post('https://public-api.shiphero.com/graphql', headers={'Authorization': f'Bearer {key}'}, json={'query': QUERY, 'variables': {'id': order_id}})
    except httpx.HTTPError:
        raise ValueError('ShipHero could not be reached. Retry the import.') from None
    if response.status_code != 200:
        raise ValueError('ShipHero could not return this order. Check the token, order ID and account permissions.')
    data = response.json()
    if data.get('errors') or not data.get('data', {}).get('wholesale_order', {}).get('data'):
        raise ValueError('ShipHero rejected the query or the order is unavailable. Verify its wholesale ID and token permissions.')
    return data
