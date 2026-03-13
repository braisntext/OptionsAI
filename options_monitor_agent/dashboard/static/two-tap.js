/**
 * Two-tap confirm pattern for mobile-friendly destructive actions.
 *
 * First tap:  button turns red with "confirm" text + countdown.
 * Second tap: executes the action.
 * Timeout:    reverts after 3 seconds if no second tap.
 *
 * Usage:
 *   <button onclick="twoTapAction(this, 'Delete item', function(){ doDelete(42); })">Delete item</button>
 */
function twoTapAction(btn, label, callback, confirmLabel) {
  if (btn.dataset.twotapArmed === '1') {
    // Second tap — execute
    btn.dataset.twotapArmed = '0';
    clearTimeout(parseInt(btn.dataset.twotapTimer, 10));
    btn.textContent = label;
    btn.classList.remove('two-tap-armed');
    callback();
    return;
  }
  // First tap — arm
  btn.dataset.twotapArmed = '1';
  btn.textContent = confirmLabel || '⚠️ Confirmar';
  btn.classList.add('two-tap-armed');
  var tid = setTimeout(function () {
    btn.dataset.twotapArmed = '0';
    btn.textContent = label;
    btn.classList.remove('two-tap-armed');
  }, 3000);
  btn.dataset.twotapTimer = String(tid);
}
