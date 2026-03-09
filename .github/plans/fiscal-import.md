# Importador Fiscal (Tax Import) — Plan

## Goal
App within Small Smart Tools that imports broker CSV statements (starting with Interactive Brokers), parses all fiscal-relevant data, displays it in organized panels, and generates instructions/files for filing the Spanish Renta (IRPF).

---

## Data Model (from IBKR CSV Analysis)

### CSV Sections to Parse
The IBKR Activity Statement CSV is multi-section with this structure:
```
SectionName,Header|Data|SubTotal|Total,Field1,Field2,...
```

### Key Sections & Fields

**1. Trades (Stocks)**
- Fields: Currency, Symbol, Date/Time, Quantity, T.Price, C.Price, Proceeds, Comm/Fee, Basis, Realized P/L, MTM P/L, Code
- Codes: O=Opening, C=Closing, A=Assignment, Ep=Expired, R=Reinvestment
- Currencies: USD, EUR, GBP

**2. Trades (Equity and Index Options)**
- Same fields as stocks
- Multiplier varies: 100 (US CBOE), 1000 (ICEEU/UK)
- Need to match open/close pairs (sell put → expires/assigned)

**3. Trades (Forex)**
- Fields: Currency, Symbol, Date/Time, Quantity, T.Price, Proceeds, Comm in EUR, MTM in EUR, Code
- AFx = AutoFX (conversion from trading, not speculative)
- Manual conversions = speculative forex trades

**4. Dividends**
- Fields: Currency, Date, Description, Amount
- Includes "Payment in Lieu of Dividend" (same tax treatment)

**5. Withholding Tax**
- Fields: Currency, Date, Description, Amount, Code
- US Tax on dividends (15% treaty rate)
- ES withholding on interest (20%)

**6. Interest**
- Fields: Currency, Date, Description, Amount
- EUR Credit Interest from cash balances

**7. Open Positions** (informational, no tax event)
- Fields: Asset Category, Currency, Symbol, Quantity, Cost Price, Cost Basis, Close Price, Value, Unrealized P/L

**8. Financial Instrument Information** (reference data)
- Fields: Symbol, Description, ISIN, Underlying, Exchange, Multiplier, Expiry, Type, Strike

**9. Deposits & Withdrawals** (informational)
**10. Grant Activity** (stock awards — special treatment)

### Sample Data Summary (2024)
| Category | Realized P/L (EUR) | Pending |
|---|---|---|
| Stocks | €0 (all still open) | €92.15 unrealized |
| Options (USD) | ~€163.19 | VZ 17JAN25 43 C open |
| Options (GBP) | ~€56.05 | — |
| Forex | -€6.92 | €0.33 unrealized |
| Dividends | €13.49 | — |
| Interest | €26.88 | — |
| US Withholding | -€2.01 | — |
| ES Withholding | -€5.38 | — |

---

## Spanish Tax Mapping (IRPF / Renta)

### Base del Ahorro — Rendimientos del Capital Mobiliario
| Concepto | Casilla | Datos |
|---|---|---|
| Intereses cuentas | 0027 | €26.88 |
| Dividendos | 0029 | €13.49 (bruto) |
| Retención en origen (US) | 0588 | €2.01 (deducción doble imposición) |
| Retención española (intereses) | Retenciones | €5.38 |

### Base del Ahorro — Ganancias y Pérdidas Patrimoniales
| Concepto | Casillas | Datos |
|---|---|---|
| Transmisión de acciones | 0328-0335 | Por cada operación cerrada |
| Transmisión de derivados (opciones) | 0328-0335 | Por cada opción cerrada |
| Ganancias/pérdidas forex | 0328-0335 | Solo forex especulativo |
| | | Cada línea: fecha adquisición, fecha transmisión, valor adquisición, valor transmisión |

### Reglas Especiales
- **Opciones expiradas (Ep)**: Fecha transmisión = fecha expiración, valor transmisión = 0, valor adquisición = prima pagada
- **Opciones vendidas (puts/calls)**: Fecha adquisición = fecha venta de la prima, valor adquisición = 0 (o prima recibida como negativo)
- **Assignment (A)**: La prima se integra en el coste de adquisición de las acciones asignadas
- **Forex AFx**: Conversiones automáticas por trading NO se declaran como ganancia forex separada — se integran en el coste de la operación subyacente
- **Forex manual**: SÍ se declara como ganancia patrimonial
- **Payment in Lieu of Dividend**: Se declara como dividendo normal
- **Stock Awards (Grant Activity)**: Tributan como rendimiento del trabajo cuando se vesting, no cuando se conceden
- **Conversión a EUR**: Usar tipo de cambio del BCE en la fecha de cada operación

---

## Phases

### Phase 1: Architecture & Data Model
- [ ] **1.1** Design database schema for imported statements (broker-agnostic)
- [ ] **1.2** Design parser interface (abstract base for future brokers)
- [ ] **1.3** Design IBKR CSV parser (section-aware, multi-currency)
- [ ] **1.4** Define API contracts for upload, data retrieval, tax calculation
- [ ] **1.5** Define EUR conversion strategy (BCE exchange rates API)

**Agent: Architect**

### Phase 2: Backend — CSV Parser & Data Import
- [ ] **2.1** Create broker parser base class with abstract methods
- [ ] **2.2** Implement IBKR CSV parser (all sections listed above)
- [ ] **2.3** Create database tables (SQLAlchemy models)
- [ ] **2.4** Implement file upload endpoint (`POST /api/fiscal/upload`)
- [ ] **2.5** Implement EUR conversion service (BCE/ECB exchange rates)
- [ ] **2.6** Store parsed data normalized to EUR with original currency preserved

**Agent: Backend**

### Phase 3: Backend — Tax Calculation Engine
- [ ] **3.1** Implement stock gains calculator (match buy/sell, FIFO)
- [ ] **3.2** Implement options gains calculator (open/close/expire/assign)
- [ ] **3.3** Implement dividend aggregator (with withholding tracking)
- [ ] **3.4** Implement interest aggregator
- [ ] **3.5** Implement forex P/L calculator (separate AFx from manual)
- [ ] **3.6** Map all results to Spanish Renta casillas
- [ ] **3.7** Handle assignment rule (prima → coste acciones)
- [ ] **3.8** API endpoints for each tax category (`/api/fiscal/stocks`, `/api/fiscal/options`, etc.)

**Agent: Backend**

### Phase 4: Frontend — Dashboard Panels
- [ ] **4.1** Create fiscal dashboard page (`/fiscal`)
- [ ] **4.2** Upload panel (drag & drop CSV, broker selector, year selector)
- [ ] **4.3** Resumen fiscal panel (overview cards: total gains, dividends, interest, taxes)
- [ ] **4.4** Panel: Operaciones con acciones (table with FIFO matching)
- [ ] **4.5** Panel: Operaciones con opciones (table with open/close pairs)
- [ ] **4.6** Panel: Dividendos y retenciones (table with withholding breakdown)
- [ ] **4.7** Panel: Intereses (table)
- [ ] **4.8** Panel: Forex (table, AFx vs manual separated)
- [ ] **4.9** Panel: Posiciones abiertas (informational, unrealized P/L)
- [ ] **4.10** Casillas de la Renta panel (mapped view: casilla → amount → instructions)

**Agent: Frontend**

### Phase 5: Export & Renta Instructions
- [ ] **5.1** Generate "Instrucciones para la Renta" document (HTML/PDF)
- [ ] **5.2** Step-by-step guide: which casilla, what to enter, screenshots/descriptions
- [ ] **5.3** Export CSV/JSON with all tax data structured by casilla
- [ ] **5.4** Downloadable summary report

**Agent: Backend + Frontend**

### Phase 6: Website Integration
- [ ] **6.1** Add "Importador Fiscal" card to landing.html apps catalogue
- [ ] **6.2** Create informational page (`/fiscal-info`) similar to alt-investments
- [ ] **6.3** Update subscribe.html pricing tiers (include fiscal app in Unlimited)
- [ ] **6.4** Add navigation links in site-nav
- [ ] **6.5** Update copilot-instructions.md with new app

**Agent: Frontend + Backend**

### Phase 7: QA & Security
- [ ] **7.1** Validate CSV upload security (file size limits, content validation, no code injection)
- [ ] **7.2** Test parser with edge cases (empty sections, partial data, multi-year)
- [ ] **7.3** Verify tax calculations against manual calculations from sample CSV
- [ ] **7.4** Verify all amounts match IBKR statement totals
- [ ] **7.5** OWASP review (file upload, auth, CSRF)
- [ ] **7.6** Accessibility and responsive design check

**Agent: QA**

---

## Dependencies
```
Phase 1 (Architecture) → Phase 2 (Parser) → Phase 3 (Tax Engine)
                                           → Phase 4 (Frontend) — can start panels with mock data
Phase 3 + Phase 4 → Phase 5 (Export)
Phase 4 → Phase 6 (Website integration) — can run in parallel with Phase 5
Phase 3 + 4 + 5 + 6 → Phase 7 (QA)
```

## Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| IBKR CSV format changes between years | Parser breaks | Version detection in parser; test with multiple years |
| BCE exchange rate API unavailable | Can't convert currencies | Cache rates locally; fallback to IBKR's own FX rates in CSV |
| Assignment rules complex (prima → stock cost) | Wrong tax calc | Manual validation against known-good examples |
| Spanish tax law changes | Wrong casillas | Configurable casilla mapping per tax year |
| Large CSV files (active traders) | Performance | Stream parsing, paginated API responses |
| Future brokers have very different formats | Hard to extend | Abstract parser interface from day 1 |

## Architecture Decisions

### Parser Design (Extensible)
```
parsers/
  base_parser.py        — Abstract BrokerParser class
  ibkr_parser.py        — IBKR CSV implementation
  # Future:
  degiro_parser.py
  trade_republic_parser.py
```

### Database Schema (Broker-Agnostic)
```
fiscal_statements     — uploaded file metadata (user, broker, year, filename)
fiscal_trades         — normalized trades (any broker)
fiscal_dividends      — normalized dividends
fiscal_interest       — normalized interest
fiscal_withholdings   — normalized tax withholdings
fiscal_forex          — normalized forex transactions
fiscal_positions      — open positions snapshot
fiscal_tax_results    — calculated tax results by casilla
exchange_rates        — cached EUR conversion rates
```

### Currency Strategy
- Store all amounts in ORIGINAL currency + EUR equivalent
- EUR conversion at BCE rate on transaction date
- Display both in the UI

## Pricing Integration
- **Free tier**: Upload 1 statement, view summary only
- **Basic (€0.95/mo)**: Upload 1 statement, all panels, basic export
- **Unlimited (€9.95/mo)**: Multiple statements, all brokers, full export with Renta instructions
