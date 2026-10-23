"""User-entered monthly bills. These cash outlays never include token estimates."""

from decimal import Decimal, InvalidOperation
from html import escape
import json
import os
from pathlib import Path
import tempfile
import threading


ACCOUNTS = (("codex", "Codex"), ("claude_a", "Claude A"), ("claude_b", "Claude B"), ("kimi", "Kimi"))
CHARGES = ("subscription", "extras", "api")
_LOCK = threading.Lock()


def _bills_path():
    base = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(base) / "clearstack" / "bills.json"


def load_bills(month):
    path = _bills_path()
    try:
        records = json.loads(path.read_text())
    except FileNotFoundError:
        records = {}
    if not isinstance(records, dict):
        raise ValueError("Bills file must contain monthly records.")
    return records.get(month, {
        "budget": None,
        "accounts": [{"id": key, **dict.fromkeys(CHARGES)} for key, _ in ACCOUNTS],
    })


def _cents(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("Enter dollar amounts with at most two decimal places.")
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number > 1_000_000 or number != number.quantize(Decimal("0.01")):
            raise ValueError("Enter a dollar amount between 0 and 1000000 with at most two decimal places.")
        return int(number * 100)
    except InvalidOperation as error:
        raise ValueError("Enter dollar amounts with at most two decimal places.") from error


def save_bills(month, payload):
    """Validate dollar inputs and atomically save integer cents without losing other months."""
    if not isinstance(payload, dict) or not isinstance(payload.get("accounts"), list):
        raise ValueError("Enter bills for all four accounts.")
    rows = payload["accounts"]
    if (len(rows) != len(ACCOUNTS) or any(not isinstance(row, dict) for row in rows)
            or {row.get("id") for row in rows} != {key for key, _ in ACCOUNTS}):
        raise ValueError("Enter bills for all four accounts.")
    record = {
        "budget": _cents(payload.get("budget")),
        "accounts": [{"id": row["id"], **{key: _cents(row.get(key)) for key in CHARGES}} for row in rows],
    }
    path = _bills_path()
    with _LOCK:
        try:
            records = json.loads(path.read_text())
        except FileNotFoundError:
            records = {}
        if not isinstance(records, dict):
            raise ValueError("Bills file must contain monthly records.")
        records[month] = record
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                json.dump(records, handle, indent=2)
                handle.write("\n")
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return record


def render_bills(month, record):
    accounts = {row["id"]: row for row in record["accounts"]}
    rows = []
    total = entered = 0
    for key, label in ACCOUNTS:
        account = accounts[key]
        cells = []
        subtotal = sum(account[field] or 0 for field in CHARGES)
        total += subtotal
        for field in CHARGES:
            value = account[field]
            entered += value is not None
            text = "" if value is None else f"{value / 100:.2f}"
            cells.append(f'<td><input type=number min=0 max=1000000 step=0.01 '
                         f'name="{key}.{field}" aria-label="{label} {field} in dollars" '
                         f'value="{text}" placeholder="Unknown"></td>')
        rows.append(f'<tr><th scope=row>{label}</th>{"".join(cells)}'
                    f'<td data-subtotal="{key}" data-sort-value="{subtotal}">${subtotal / 100:,.2f}</td></tr>')
    budget = record["budget"]
    budget_input = "" if budget is None else f"{budget / 100:.2f}"
    return f"""<section class=billing id=spending>
      <div class=section-heading><h2>Your monthly bills</h2><span>USD · {escape(month)}</span></div>
      <div class=cards><div class=card><b id=bills-total>${total / 100:,.2f}</b><span>recorded cash outlay</span></div>
      <div class=card><b id=bills-coverage>{entered}/12</b><span>charge fields entered</span></div>
      <div class=card><b id=budget-remaining>Not set</b><span>budget minus recorded charges</span></div></div>
      <form id=bills-form data-month="{escape(month)}">
      <div class=table-scroll><table class=bills data-sortable><thead><tr><th>Account</th><th data-sort=number>Subscription $</th>
      <th data-sort=number>Extras / top-ups $</th><th data-sort=number>API charges $</th><th data-sort=number>Recorded total</th></tr></thead>
      <tbody>{''.join(rows)}</tbody></table></div>
      <div class=actions><label>Monthly budget $ <input name=budget type=number min=0 max=1000000 step=0.01
      value="{budget_input}" placeholder="Optional"></label><button type=submit>Save bills</button>
      <span id=bills-status role=status aria-live=polite></span></div></form>
      <p class=quota-note>Enter invoices or payments for this month. Blank means unknown; enter 0 to confirm no charge.
      Top-ups count when purchased. Avoid entering the same charge in both extras and API charges.
      Totals stay partial until all fields are filled. Budget tracking does not stop agents.</p>
    </section>"""


BILLS_SCRIPT = """<script>
(() => {
  const form = document.getElementById('bills-form');
  if (!form) return;
  const fields = ['subscription', 'extras', 'api'];
  const ids = ['codex', 'claude_a', 'claude_b', 'kimi'];
  const status = document.getElementById('bills-status');
  const money = cents => (cents / 100).toLocaleString('en-US', {style: 'currency', currency: 'USD'});
  function update() {
    let total = 0, entered = 0;
    ids.forEach(id => {
      let subtotal = 0;
      fields.forEach(key => {
        const value = form.elements.namedItem(id + '.' + key).value;
        if (value !== '') { entered++; subtotal += Math.round(Number(value) * 100); }
      });
      total += subtotal;
      const cell = document.querySelector('[data-subtotal="' + id + '"]');
      cell.textContent = money(subtotal);
      cell.dataset.sortValue = String(subtotal);
    });
    document.getElementById('bills-total').textContent = money(total);
    document.getElementById('bills-coverage').textContent = entered + '/12';
    const budget = form.elements.namedItem('budget').value;
    const remaining = document.getElementById('budget-remaining');
    remaining.textContent = budget === '' ? 'Not set' : money(Math.round(Number(budget) * 100) - total);
    remaining.classList.toggle('over-budget', budget !== '' && total > Number(budget) * 100);
  }
  form.addEventListener('input', () => { update(); status.textContent = 'Unsaved changes'; });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button');
    button.disabled = true;
    status.textContent = 'Saving…';
    try {
      const response = await fetch('/api/bills', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({month: form.dataset.month, budget: form.elements.namedItem('budget').value,
          accounts: ids.map(id => Object.fromEntries([['id', id], ...fields.map(key =>
            [key, form.elements.namedItem(id + '.' + key).value])]))})
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Save failed');
      status.textContent = 'Saved on this Mac';
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  });
  update();
})();
</script>"""
