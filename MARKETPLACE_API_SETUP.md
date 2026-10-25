# QOR Marketplace API setup

## Kaspi
Accounts → Kaspi → shield → paste API token → Save → Check and sync.
Supports live order reads and Kaspi order status actions exposed in QOR.

## Wildberries
Accounts → Wildberries → shield → paste seller API token → Save → Check and sync.
QOR calls the live Marketplace API and reads new FBS orders. The token must include the Marketplace/order access category required by Wildberries.

## Ozon
Accounts → Ozon → shield → enter Client ID + API Key → Save → Check and sync.
QOR checks both FBS and FBO posting flows for the previous 14 days. The key must have the relevant Seller API permissions.

Never put marketplace secrets in GitHub or frontend code. QOR stores site-entered credentials encrypted in the database.
