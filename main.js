document.addEventListener("DOMContentLoaded", function() {
    
    // --- 1. SIDEBAR & MOBILE MENU LOGIC ---
    const sidebar = document.querySelector('.sidebar');
    const toggleBtn = document.getElementById('sidebarToggle');
    const body = document.body;

    let overlay = document.querySelector('.sidebar-overlay');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.className = 'sidebar-overlay';
        overlay.style.cssText = "position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(0,0,0,0.5);z-index:1500;display:none;";
        body.appendChild(overlay);
    }

    function toggleSidebar() {
        sidebar.classList.toggle('active');
        overlay.style.display = sidebar.classList.contains('active') ? 'block' : 'none';
    }

    if (toggleBtn) {
        toggleBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            toggleSidebar();
        });
    }

    overlay.addEventListener('click', toggleSidebar);

    // Swipe Gestures
    let touchStartX = 0;
    document.addEventListener('touchstart', e => { touchStartX = e.changedTouches[0].screenX; }, {passive: true});
    document.addEventListener('touchend', e => {
        let touchEndX = e.changedTouches[0].screenX;
        let diff = touchEndX - touchStartX;
        if (diff > 100 && touchStartX < 50) toggleSidebar(); 
        if (diff < -100 && sidebar.classList.contains('active')) toggleSidebar(); 
    }, {passive: true});

    // --- 2. AUTO-DISMISS ALERTS (IGNORE .keep-alert) ---
    setTimeout(() => {
        document.querySelectorAll('.alert:not(.keep-alert)').forEach(a => {
            a.style.transition = 'opacity 0.5s ease';
            a.style.opacity = '0';
            setTimeout(() => a.remove(), 500);
        });
    }, 4000);

    // --- 3. INITIALIZE CART FOR SAFE EDIT ---
    if (typeof cart !== 'undefined' && Object.keys(cart).length > 0) {
        updateCartUI();
        if (typeof editCust !== 'undefined' && editCust !== "None" && editCust !== "") { 
            document.getElementById('customerSelect').value = editCust; 
        }
        if (typeof editPaid !== 'undefined' && editPaid !== "") { 
            document.getElementById('amountPaidInput').value = editPaid; 
        }
        calculateScenario();
    }
});


// --- POS FUNCTIONS ---

function closeReceipt() { 
    document.getElementById('invoiceModal').style.display = 'none'; 
    window.history.replaceState({}, document.title, window.location.pathname);
}

function searchItems() {
    let input = document.getElementById('itemSearch').value.toLowerCase();
    let cards = document.getElementsByClassName('product-card-container');
    for (let card of cards) {
        let name = card.getAttribute('data-name');
        let size = card.getAttribute('data-size');
        card.style.display = (name.includes(input) || size.includes(input)) ? "" : "none";
    }
}

// Added maxStock parameter to prevent selling more than inventory
function addToCart(id, name, price, maxStock) {
    if (cart[id]) {
        // Enforce limit if we know it (fallback to 999 for editing old items)
        let limit = maxStock !== undefined ? maxStock : (cart[id].maxStock || 999);
        if (cart[id].qty < limit) {
            cart[id].qty += 1;
        } else {
            alert("Only " + limit + " items left in stock!");
        }
    } else {
        if (maxStock > 0 || maxStock === undefined) {
            cart[id] = { name: name, price: price, qty: 1, maxStock: maxStock };
        } else {
            alert("This item is out of stock!");
        }
    }
    updateCartUI();
}

function adjustQty(id, change) {
    if (cart[id]) {
        let newQty = cart[id].qty + change;
        let limit = cart[id].maxStock || 999;
        
        // Enforce limit on the '+' button
        if (newQty > limit) {
            alert("Cannot exceed available stock (" + limit + ").");
            return;
        }
        
        cart[id].qty = newQty;
        if (cart[id].qty <= 0) { delete cart[id]; }
        updateCartUI();
    }
}

function clearCart() { 
    cart = {}; 
    updateCartUI(); 
}

function updateCartUI() {
    const tbody = document.getElementById('cartBody');
    const completeBtn = document.getElementById('completeBtn');
    
    if (Object.keys(cart).length === 0) {
        tbody.innerHTML = '<tr><td class="text-center py-5 text-muted">Tap an item to add to bag</td></tr>';
        document.getElementById('displayTotal').innerText = "0 MMK";
        document.getElementById('formTotalAmount').value = 0;
        document.getElementById('amountPaidInput').value = 0;
        document.getElementById('formCartData').value = "";
        completeBtn.disabled = true;
        return;
    }

    tbody.innerHTML = '';
    let total = 0;
    let cartDataString = [];
    
    for (const [id, item] of Object.entries(cart)) {
        let subtotal = item.price * item.qty;
        total += subtotal;
        cartDataString.push(`${id}:${item.qty}`); 
        tbody.innerHTML += `
            <tr class="border-bottom">
                <td class="ps-3 py-2">
                    <div class="fw-bold small">${item.name}</div>
                    <div class="text-muted smaller">${item.price.toLocaleString()} MMK</div>
                </td>
                <td style="width: 110px;">
                    <div class="input-group input-group-sm">
                        <button type="button" class="btn btn-outline-secondary" onclick="adjustQty('${id}', -1)">-</button>
                        <input type="text" class="form-control text-center bg-white" value="${item.qty}" readonly>
                        <button type="button" class="btn btn-outline-secondary" onclick="adjustQty('${id}', 1)">+</button>
                    </div>
                </td>
                <td class="text-end pe-3 small fw-bold">${subtotal.toLocaleString()}</td>
            </tr>`;
    }
    
    document.getElementById('displayTotal').innerText = total.toLocaleString() + " MMK";
    document.getElementById('formTotalAmount').value = total;
    document.getElementById('formCartData').value = cartDataString.join(',');
    
    // Auto-fill payment if user isn't currently typing in the box
    if(document.activeElement !== document.getElementById('amountPaidInput')){
        document.getElementById('amountPaidInput').value = total; 
    }
    
    completeBtn.disabled = false;
    calculateScenario();
}

function calculateScenario() {
    const selectElement = document.getElementById('customerSelect');
    const scenarioBox = document.getElementById('creditScenarioBox');
    
    if (!selectElement || !selectElement.value) { 
        if(scenarioBox) scenarioBox.classList.add('d-none'); 
        return; 
    }

    const selected = selectElement.options[selectElement.selectedIndex];
    const currentBalance = parseFloat(selected.getAttribute('data-balance')); 
    const totalDue = parseFloat(document.getElementById('formTotalAmount').value) || 0;
    const amountPaid = parseFloat(document.getElementById('amountPaidInput').value) || 0;
    const projectedBalance = currentBalance + (totalDue - amountPaid);

    scenarioBox.classList.remove('d-none');
    scenarioBox.innerHTML = `
        <div class="d-flex justify-content-between"><span>Current:</span> <b>${currentBalance.toLocaleString()} MMK</b></div>
        <div class="d-flex justify-content-between"><span>New:</span> <b class="${projectedBalance > 0 ? 'text-danger' : 'text-success'}">${projectedBalance.toLocaleString()} MMK</b></div>`;
}
