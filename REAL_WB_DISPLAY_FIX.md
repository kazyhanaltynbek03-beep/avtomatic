# Real marketplace data display fix

- Marketplace rows are now enriched from the existing canonical marketplace-product mapping.
- Wildberries sales that omit a product title can display the mapped ERP/catalogue product name.
- Wildberries statistics sale rows infer quantity=1 where the API sale record represents one sold unit.
- No synthetic prices, costs, FX rates, or profit are invented.
- Foreign-currency financial posting still requires the account settlement FX rate before KZT ERP posting.
- Backend regression: 141 passed.
