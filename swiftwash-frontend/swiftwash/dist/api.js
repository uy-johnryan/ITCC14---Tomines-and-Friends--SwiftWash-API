// SwiftWash API adapter. Demo data stays in this browser and never reaches your server.
const KEYS = { settings: 'swiftwash.settings.v1', token: 'swiftwash.token', user: 'swiftwash.user', demo: 'swiftwash.demo.v2' };
const id = n => n.toString(16).padStart(24, '0');
const clone = value => JSON.parse(JSON.stringify(value));
const stamp = () => new Date().toISOString();
const day = (offset, hour = 10) => { const d = new Date(); d.setDate(d.getDate() + offset); d.setHours(hour, 0, 0, 0); return d.toISOString(); };
function read(storage, key, fallback) { try { return JSON.parse(storage.getItem(key)) ?? fallback; } catch { return fallback; } }
function write(storage, key, value) { try { storage.setItem(key, JSON.stringify(value)); } catch { /* Private browsing can disable storage. */ } }
function remove(storage, key) { try { storage.removeItem(key); } catch { /* Storage is optional. */ } }
const browserLocal = globalThis.localStorage;
const browserSession = globalThis.sessionStorage;
const initialUser = { id: id(100), name: 'Alex Morgan', email: 'customer@swiftwash.demo', role: 'customer', isActive: true, address: { street: '24 Maple Avenue', city: 'New York' } };
const location = { street: '128 West 23rd Street', city: 'New York', latitude: 40.7424, longitude: -73.9954 };
export const DEMO_PARTNERS = [
  { id: id(10), userId: id(101), businessName: 'The Laundry Room', description: 'Thoughtful care for your everyday favorites.', location, rating: 4.9, ratingCount: 128, isApproved: true },
  { id: id(11), userId: id(105), businessName: 'Fresh & Fold', description: 'A little freshness, a little more free time.', location: { ...location, street: '86 Spring Street' }, rating: 4.8, ratingCount: 96, isApproved: true },
  { id: id(12), userId: id(106), businessName: 'Pure Clean Studio', description: 'Expert garment care, right in your neighborhood.', location: { ...location, street: '31 East 12th Street' }, rating: 4.9, ratingCount: 74, isApproved: true }
].map(p => ({ ...p, createdAt: day(-60), updatedAt: day(-2) }));
export const DEMO_SERVICES = DEMO_PARTNERS.flatMap((p, i) => [
  { id: id(200 + i * 3), partnerId: p.id, type: 'wash', name: 'Wash & Fold', price: [3.5, 3, 4][i], unit: 'kg', isAvailable: true },
  { id: id(201 + i * 3), partnerId: p.id, type: 'dry', name: 'Dry Cleaning', price: [8, 7.5, 9][i], unit: 'piece', isAvailable: true },
  { id: id(202 + i * 3), partnerId: p.id, type: 'fold', name: 'Iron & Fold', price: [2.5, 2, 3][i], unit: 'piece', isAvailable: true }
].map(s => ({ ...s, createdAt: day(-60), updatedAt: day(-2) })));
function demoItem(serviceIndex, quantity, actual = null) {
  const s = DEMO_SERVICES[serviceIndex];
  return { id: id(500 + serviceIndex), serviceId: s.id, type: s.type, name: s.name, unit: s.unit, description: '', estimatedQuantity: quantity, actualQuantity: actual, unitPrice: s.price, subtotal: (actual ?? quantity) * s.price };
}
export const DEMO_ORDERS = [
  { id: id(1001), partnerId: id(10), riderId: id(102), items: [demoItem(0, 5)], pickupDate: day(0, 14), deliveryDate: day(2, 16), status: 'confirmed', fulfillmentStage: 'out_for_pickup', estimatedTotal: 17.5, finalTotal: null, totalPrice: 17.5, createdAt: day(-1) },
  { id: id(1002), partnerId: id(11), riderId: null, items: [demoItem(4, 3)], pickupDate: day(2, 10), deliveryDate: day(4, 17), status: 'pending', fulfillmentStage: 'not_started', estimatedTotal: 22.5, finalTotal: null, totalPrice: 22.5, createdAt: day(-2) },
  { id: id(1003), partnerId: id(10), riderId: id(102), items: [demoItem(0, 6, 6)], pickupDate: day(-6), deliveryDate: day(-4, 16), status: 'completed', fulfillmentStage: 'delivered', estimatedTotal: 21, finalTotal: 21, totalPrice: 21, createdAt: day(-7) }
].map(o => ({ ...o, customerId: initialUser.id, pickupAddress: clone(initialUser.address), deliveryAddress: clone(initialUser.address), specialInstructions: '', updatedAt: o.createdAt, statusHistory: [{ kind: 'status', from: null, to: 'pending', note: 'Order booked.', updatedBy: { id: initialUser.id, name: initialUser.name, role: 'customer' }, timestamp: o.createdAt }] }));
const seed = () => ({ users: [initialUser, { id: id(101), role: 'partner', name: 'Jamie Chen', email: 'partner@swiftwash.demo', isActive: true }, { id: id(102), role: 'rider', name: 'Sam Taylor', email: 'rider@swiftwash.demo', isActive: true }, { id: id(103), role: 'admin', name: 'Jordan Lee', email: 'admin@swiftwash.demo', isActive: true }], partners: clone(DEMO_PARTNERS), services: clone(DEMO_SERVICES), orders: clone(DEMO_ORDERS), reviews: [] });
let settings = read(browserLocal, KEYS.settings, { demo: true, baseUrl: 'http://localhost:5000/api/v1' });
let data = read(browserLocal, KEYS.demo, null) || seed();
let current = read(browserSession, KEYS.user, null);
if (settings.demo && !current) current = clone(initialUser);
let accessToken = read(browserSession, KEYS.token, null);
function persist() { write(browserLocal, KEYS.demo, data); }
function session(user, token = null) { current = user; accessToken = token; write(browserSession, KEYS.user, user); write(browserSession, KEYS.token, token); return user; }
function fail(message, status = 422, details) { const e = new Error(message); e.status = status; e.details = details; throw e; }
function requireUser(...roles) { if (!current) fail('Please sign in to continue.', 401); if (roles.length && !roles.includes(current.role)) fail('You do not have permission to perform this action.', 403); return current; }
function makeId() { return Array.from(crypto.getRandomValues(new Uint8Array(12)), n => n.toString(16).padStart(2, '0')).join(''); }
function history(o, kind, old, next, note = '') { o.statusHistory ??= []; o.statusHistory.push({ kind, from: old == null ? null : String(old), to: String(next), note, updatedBy: { id: current.id, name: current.name, role: current.role }, timestamp: stamp() }); o.updatedAt = stamp(); }
function paginated(rows, query) { const page = Math.max(1, Number(query.get('page')) || 1), limit = Math.min(100, Math.max(1, Number(query.get('limit')) || 10)); return { data: clone(rows.slice((page - 1) * limit, page * limit)), meta: { page, limit, total: rows.length, totalPages: Math.ceil(rows.length / limit) } }; }
function ownPartner() { return data.partners.find(p => p.userId === current?.id); }
function authorizeOrder(o) { requireUser(); if (current.role === 'admin' || (current.role === 'customer' && o.customerId === current.id) || (current.role === 'rider' && o.riderId === current.id) || (current.role === 'partner' && ownPartner()?.id === o.partnerId)) return; fail('You do not have permission to access this order.', 403); }
function buildItems(partnerId, items) {
  if (!Array.isArray(items) || !items.length) fail('Select at least one service.');
  return items.map((item, i) => {
    const s = data.services.find(s => s.id === item.serviceId && s.partnerId === partnerId);
    if (!s || !s.isAvailable) fail('A selected service is unavailable.', 409);
    const q = Number(item.estimatedQuantity);
    if (!Number.isFinite(q) || q < 0.5 || (s.unit !== 'kg' && !Number.isInteger(q))) fail(`Enter a valid quantity for ${s.name}.`);
    return { id: makeId(), serviceId: s.id, type: s.type, name: s.name, unit: s.unit, description: String(item.description || '').slice(0, 200), estimatedQuantity: q, actualQuantity: null, unitPrice: s.price, subtotal: Math.round(q * s.price * 100) / 100 };
  });
}
function validateDates(d) { const p = Date.parse(d.pickupDate), e = Date.parse(d.deliveryDate); if (!Number.isFinite(p) || !Number.isFinite(e) || p <= Date.now() || e <= p) fail('Pickup must be in the future and delivery must be later.'); }
function validateAddress(a) { if (!a || typeof a.street !== 'string' || !a.street.trim() || typeof a.city !== 'string' || !a.city.trim()) fail('Street and city are required.'); return clone(a); }
function recalc(partnerId) { const p = data.partners.find(p => p.id === partnerId), r = data.reviews.filter(r => r.partnerId === partnerId); if (p) { p.ratingCount = r.length; p.rating = r.length ? Math.round(r.reduce((n, r) => n + r.rating, 0) / r.length * 100) / 100 : 0; } }
async function demoRequest(path, { method = 'GET', body = {} } = {}) {
  const url = new URL(path.replace(/^\/api\/v1(?=\/|$)/, '') || '/', 'https://demo.local');
  const parts = url.pathname.replace(/\/$/, '').split('/').filter(Boolean), [resource, recordId, action] = parts, q = url.searchParams;
  method = method.toUpperCase();
  if (resource === 'health') return { status: 'ok', database: 'demo', timestamp: stamp() };
  if (resource === 'auth') {
    if (recordId === 'login') {
      if (!body.email || !body.password) fail('Enter your email and password.');
      const u = data.users.find(u => u.email.toLowerCase() === String(body.email).trim().toLowerCase());
      if (!u) fail('Use a demo account or create an account in this browser.', 401);
      if (!u.isActive) fail('This account has been deactivated.', 403);
      session(clone(u), 'demo'); return { token: 'demo', user: clone(u) };
    }
    if (recordId === 'register') {
      if (!['customer', 'partner', 'rider'].includes(body.role) || !body.name?.trim() || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(body.email || '') || String(body.password || '').length < 8) fail('Enter a name, valid email, and password of at least 8 characters.');
      if (data.users.some(u => u.email.toLowerCase() === body.email.toLowerCase())) fail('An account with this email already exists.', 409);
      const u = { id: makeId(), role: body.role, name: body.name.trim(), email: body.email.toLowerCase(), isActive: true, createdAt: stamp(), updatedAt: stamp() };
      if (body.address) u.address = validateAddress(body.address);
      data.users.push(u); persist(); session(clone(u), 'demo'); return { token: 'demo', user: clone(u) };
    }
  }
  if (resource === 'users') {
    requireUser();
    if (recordId === 'me') return clone(data.users.find(u => u.id === current.id) || current);
    if (!recordId) { requireUser('admin'); let rows = data.users; if (q.has('role')) rows = rows.filter(u => u.role === q.get('role')); if (q.has('isActive')) rows = rows.filter(u => u.isActive === (q.get('isActive') === 'true')); if (q.has('search')) rows = rows.filter(u => `${u.name} ${u.email}`.toLowerCase().includes(q.get('search').toLowerCase())); return paginated(rows, q); }
    const u = data.users.find(u => u.id === recordId); if (!u) fail('User not found.', 404);
    if (current.role !== 'admin' && current.id !== u.id) fail('Not allowed.', 403);
    if (method === 'PATCH') { for (const key of ['name', 'address']) if (key in body) u[key] = key === 'address' ? validateAddress(body[key]) : String(body[key]).trim(); if (current.role === 'admin') for (const key of ['role', 'isActive']) if (key in body) u[key] = body[key]; u.updatedAt = stamp(); persist(); if (u.id === current.id) session(clone(u), accessToken); }
    if (method === 'DELETE') { requireUser('admin'); data.users = data.users.filter(x => x.id !== u.id); persist(); return null; }
    return clone(u);
  }
  if (resource === 'partners') {
    if (!recordId) {
      if (method === 'POST') { requireUser('partner'); if (ownPartner()) fail('Partner profile already exists.', 409); if (!body.businessName?.trim()) fail('Business name is required.'); const p = { id: makeId(), userId: current.id, businessName: body.businessName.trim(), description: body.description || '', location: validateAddress(body.location), rating: 0, ratingCount: 0, isApproved: false, createdAt: stamp(), updatedAt: stamp() }; data.partners.push(p); persist(); return clone(p); }
      let rows = data.partners.filter(p => current?.role === 'admin' || (q.get('mine') === 'true' ? p.userId === current?.id : p.isApproved));
      if (q.has('isApproved') && current?.role === 'admin') rows = rows.filter(p => p.isApproved === (q.get('isApproved') === 'true'));
      if (q.has('search')) rows = rows.filter(p => p.businessName.toLowerCase().includes(q.get('search').toLowerCase()));
      if (q.has('minRating')) rows = rows.filter(p => p.rating >= Number(q.get('minRating')));
      return paginated(rows.sort((a, b) => b.rating - a.rating), q);
    }
    const p = data.partners.find(p => p.id === recordId); if (!p) fail('Partner not found.', 404);
    if (!p.isApproved && current?.role !== 'admin' && p.userId !== current?.id) fail('Partner not found.', 404);
    if (action === 'services') return paginated(data.services.filter(s => s.partnerId === p.id && (s.isAvailable || current?.role === 'admin' || p.userId === current?.id)), q);
    if (action === 'reviews') return paginated(data.reviews.filter(r => r.partnerId === p.id), q);
    if (method !== 'GET') { requireUser(); if (action === 'approval') requireUser('admin'); else if (current.role !== 'admin' && p.userId !== current.id) fail('Partner owner or admin only.', 403); }
    if (method === 'PUT') Object.assign(p, { businessName: body.businessName, description: body.description || '', location: validateAddress(body.location), updatedAt: stamp() });
    if (method === 'PATCH' && action === 'approval') { if (typeof body.isApproved !== 'boolean') fail('Approval must be true or false.'); p.isApproved = body.isApproved; }
    if (method === 'DELETE') { if (data.orders.some(o => o.partnerId === p.id && ['pending', 'confirmed', 'inprogress'].includes(o.status))) fail('Partner has active orders.', 409); data.partners = data.partners.filter(x => x.id !== p.id); data.services = data.services.filter(s => s.partnerId !== p.id); persist(); return null; }
    persist(); return clone(p);
  }
  if (resource === 'services') {
    if (!recordId) {
      if (method === 'POST') { requireUser('partner'); const p = ownPartner(); if (!p) fail('Create a partner profile first.', 403); if (!['wash', 'dry', 'fold'].includes(body.type) || !body.name?.trim() || !Number.isFinite(Number(body.price)) || Number(body.price) < 0) fail('Enter valid service details.'); const s = { id: makeId(), partnerId: p.id, type: body.type, name: body.name.trim(), price: Number(body.price), unit: body.unit || 'kg', isAvailable: body.isAvailable ?? true, createdAt: stamp(), updatedAt: stamp() }; data.services.push(s); persist(); return clone(s); }
      let rows = data.services.filter(s => { const p = data.partners.find(p => p.id === s.partnerId); return p && ((p.isApproved && s.isAvailable) || current?.role === 'admin' || p.userId === current?.id); });
      if (q.has('partnerId')) rows = rows.filter(s => s.partnerId === q.get('partnerId'));
      if (q.has('type')) rows = rows.filter(s => s.type === q.get('type'));
      if (q.has('maxPrice')) rows = rows.filter(s => s.price <= Number(q.get('maxPrice')));
      return paginated(rows, q);
    }
    const s = data.services.find(s => s.id === recordId); if (!s) fail('Service not found.', 404);
    if (method !== 'GET') { requireUser(); if (current.role !== 'admin' && ownPartner()?.id !== s.partnerId) fail('Partner owner or admin only.', 403); }
    if (method === 'PUT') Object.assign(s, { type: body.type, name: body.name, price: Number(body.price), unit: body.unit || 'kg', isAvailable: body.isAvailable ?? true, updatedAt: stamp() });
    if (method === 'DELETE') { if (data.orders.some(o => ['pending', 'confirmed', 'inprogress'].includes(o.status) && o.items.some(i => i.serviceId === s.id))) fail('Service is used by an active order.', 409); data.services = data.services.filter(x => x.id !== s.id); persist(); return null; }
    persist(); return clone(s);
  }
  if (resource === 'riders') { requireUser('partner', 'admin'); let rows = data.users.filter(u => u.role === 'rider' && u.isActive).map(u => ({ id: u.id, name: u.name, isAvailable: !data.orders.some(o => o.riderId === u.id && ['out_for_pickup', 'out_for_delivery'].includes(o.fulfillmentStage)), activeOrderCount: data.orders.filter(o => o.riderId === u.id && ['pending', 'confirmed', 'inprogress'].includes(o.status)).length })); if (q.get('available') === 'true') rows = rows.filter(u => u.isAvailable); if (q.has('search')) rows = rows.filter(u => u.name.toLowerCase().includes(q.get('search').toLowerCase())); return paginated(rows, q); }
  if (resource === 'orders') {
    requireUser();
    if (!recordId) {
      if (method === 'POST') {
        requireUser('customer'); const p = data.partners.find(p => p.id === body.partnerId && p.isApproved); if (!p) fail('Choose an approved laundry partner.'); validateDates(body); const items = buildItems(p.id, body.items), total = Math.round(items.reduce((n, i) => n + i.subtotal, 0) * 100) / 100;
        const o = { id: makeId(), customerId: current.id, partnerId: p.id, riderId: null, items, pickupDate: body.pickupDate, deliveryDate: body.deliveryDate, pickupAddress: validateAddress(body.pickupAddress), deliveryAddress: validateAddress(body.deliveryAddress || body.pickupAddress), specialInstructions: body.specialInstructions || '', status: 'pending', fulfillmentStage: 'not_started', estimatedTotal: total, finalTotal: null, totalPrice: total, statusHistory: [], createdAt: stamp(), updatedAt: stamp() }; history(o, 'status', null, 'pending', 'Order booked.'); data.orders.unshift(o); persist(); return clone(o);
      }
      let rows = data.orders.filter(o => current.role === 'admin' || (current.role === 'customer' && o.customerId === current.id) || (current.role === 'partner' && ownPartner()?.id === o.partnerId) || (current.role === 'rider' && o.riderId === current.id));
      for (const key of ['status', 'fulfillmentStage', 'riderId', 'partnerId']) if (q.has(key)) rows = rows.filter(o => o[key] === q.get(key));
      return paginated(rows.sort((a, b) => b.createdAt.localeCompare(a.createdAt)), q);
    }
    const o = data.orders.find(o => o.id === recordId); if (!o) fail('Order not found.', 404); authorizeOrder(o);
    if (method === 'DELETE') { if (current.role !== 'admin' && !(current.role === 'customer' && ['pending', 'cancelled'].includes(o.status))) fail('This order cannot be deleted.', 409); data.orders = data.orders.filter(x => x.id !== o.id); persist(); return null; }
    if (method === 'PUT') { if (!['customer', 'admin'].includes(current.role) || o.status !== 'pending') fail('Only pending orders can be edited.', 409); validateDates(body); const items = buildItems(o.partnerId, body.items), total = Math.round(items.reduce((n, i) => n + i.subtotal, 0) * 100) / 100; Object.assign(o, { items, pickupDate: body.pickupDate, deliveryDate: body.deliveryDate, pickupAddress: validateAddress(body.pickupAddress), deliveryAddress: validateAddress(body.deliveryAddress || body.pickupAddress), specialInstructions: body.specialInstructions || '', estimatedTotal: total, totalPrice: total, finalTotal: null, updatedAt: stamp() }); }
    if (method === 'PATCH') {
      if (action === 'status') { const next = body.status; if (!['confirmed', 'cancelled'].includes(next)) fail('Only confirmed or cancelled may be set here.'); if ((next === 'confirmed' && (!['partner', 'admin'].includes(current.role) || o.status !== 'pending')) || (next === 'cancelled' && (!['customer', 'partner', 'admin'].includes(current.role) || !['pending', 'confirmed'].includes(o.status)))) fail('Invalid order status transition.', 409); history(o, 'status', o.status, next, body.note); o.status = next; }
      else if (action === 'rider') { requireUser('partner', 'admin'); if (!['confirmed', 'inprogress'].includes(o.status)) fail('Order is not assignable.', 409); if (current.role !== 'admin' && ['out_for_pickup', 'out_for_delivery'].includes(o.fulfillmentStage)) fail('Rider cannot be reassigned during a trip.', 409); const r = data.users.find(r => r.id === body.riderId && r.role === 'rider' && r.isActive); if (!r) fail('Select an active rider.'); if (data.orders.some(x => x.id !== o.id && x.riderId === r.id && ['out_for_pickup', 'out_for_delivery'].includes(x.fulfillmentStage))) fail('Rider is currently on another trip.', 409); history(o, 'rider_assignment', o.riderId, r.id, body.note); o.riderId = r.id; }
      else if (action === 'fulfillment') { const stages = ['not_started', 'out_for_pickup', 'picked_up', 'ready_for_delivery', 'out_for_delivery', 'delivered'], next = body.stage; if (stages.indexOf(next) !== stages.indexOf(o.fulfillmentStage) + 1) fail('Fulfillment stages must advance one step at a time.', 409); if (current.role !== 'admin' && !(next === 'ready_for_delivery' ? current.role === 'partner' : current.role === 'rider')) fail(next === 'ready_for_delivery' ? 'Partner only.' : 'Assigned rider only.', 403); if (next === 'out_for_pickup' && (o.status !== 'confirmed' || !o.riderId)) fail('Order must be confirmed with a rider assigned.', 409); if (next === 'ready_for_delivery' && o.items.some(i => i.actualQuantity == null)) fail('Record actual quantities first.', 409); history(o, 'fulfillment', o.fulfillmentStage, next, body.note); o.fulfillmentStage = next; if (next === 'picked_up' || next === 'delivered') { const status = next === 'picked_up' ? 'inprogress' : 'completed'; history(o, 'status', o.status, status); o.status = status; } }
      else if (action === 'actual-quantities') { requireUser('partner', 'admin'); if (o.status !== 'inprogress' || o.fulfillmentStage !== 'picked_up') fail('Quantities can only be recorded after pickup and before ready for delivery.', 409); if (!Array.isArray(body.items) || body.items.length !== o.items.length || new Set(body.items.map(i => i.itemId)).size !== o.items.length) fail('Exactly one quantity is required for every order item.'); for (const item of o.items) { const qty = Number(body.items.find(i => i.itemId === item.id)?.actualQuantity); if (!Number.isFinite(qty) || qty < 0.1 || (item.unit !== 'kg' && !Number.isInteger(qty))) fail('Enter a valid actual quantity.'); item.actualQuantity = qty; item.subtotal = Math.round(qty * item.unitPrice * 100) / 100; } const total = Math.round(o.items.reduce((n, i) => n + i.subtotal, 0) * 100) / 100; history(o, 'weights_recorded', o.totalPrice, total, body.note); o.finalTotal = total; o.totalPrice = total; }
      else fail('Route not found.', 404);
    }
    persist(); return clone(o);
  }
  if (resource === 'reviews') {
    if (!recordId) {
      if (method === 'POST') { requireUser('customer'); const o = data.orders.find(o => o.id === body.orderId); if (!o) fail('Order not found.', 404); if (o.customerId !== current.id) fail('You do not own this order.', 403); if (o.status !== 'completed') fail('Only completed orders can be reviewed.', 409); if (data.reviews.some(r => r.orderId === o.id)) fail('This order has already been reviewed.', 409); if (!Number.isInteger(body.rating) || body.rating < 1 || body.rating > 5) fail('Rating must be an integer from 1 to 5.'); const r = { id: makeId(), customerId: current.id, partnerId: o.partnerId, orderId: o.id, rating: body.rating, comment: String(body.comment || '').slice(0, 1000), createdAt: stamp(), updatedAt: stamp() }; data.reviews.unshift(r); recalc(o.partnerId); persist(); return clone(r); }
      let rows = data.reviews.filter(r => data.partners.find(p => p.id === r.partnerId)?.isApproved || current?.role === 'admin'); for (const key of ['partnerId', 'customerId']) if (q.has(key)) rows = rows.filter(r => r[key] === q.get(key)); if (q.has('minRating')) rows = rows.filter(r => r.rating >= Number(q.get('minRating'))); return paginated(rows, q);
    }
    const r = data.reviews.find(r => r.id === recordId); if (!r) fail('Review not found.', 404);
    if (method !== 'GET') { requireUser(); if (current.role !== 'admin' && !(current.role === 'customer' && r.customerId === current.id)) fail('Review author or admin only.', 403); }
    if (method === 'PATCH') { if ('rating' in body) { if (!Number.isInteger(body.rating) || body.rating < 1 || body.rating > 5) fail('Rating must be an integer from 1 to 5.'); r.rating = body.rating; } if ('comment' in body) r.comment = String(body.comment).slice(0, 1000); r.updatedAt = stamp(); }
    if (method === 'DELETE') data.reviews = data.reviews.filter(x => x.id !== r.id);
    recalc(r.partnerId); persist(); return method === 'DELETE' ? null : clone(r);
  }
  fail('Route not found.', 404);
}
export const api = {
  get mode() { return settings.demo ? 'demo' : 'live'; },
  get baseUrl() { return settings.baseUrl; },
  get user() { return current ? clone(current) : null; },
  configure({ baseUrl = settings.baseUrl, demo = settings.demo } = {}) {
    const url = new URL(String(baseUrl).trim());
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) fail('Enter an HTTP or HTTPS API URL without credentials, a query, or a fragment.');
    const normalized = url.href.replace(/\/$/, '').replace(/\/api\/v1$/, '') + '/api/v1';
    const changed = settings.demo !== Boolean(demo) || settings.baseUrl !== normalized;
    settings = { demo: Boolean(demo), baseUrl: normalized }; write(browserLocal, KEYS.settings, settings);
    if (changed) { session(settings.demo ? clone(initialUser) : null); }
    return { ...settings };
  },
  async request(path, options = {}) {
    if (settings.demo) return demoRequest(path, options);
    const cleanPath = String(path).replace(/^\/api\/v1(?=\/|$)/, '').replace(/^\//, '');
    const method = (options.method || 'GET').toUpperCase();
    const headers = { Accept: 'application/json' };
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
    let response;
    try { response = await fetch(`${settings.baseUrl}/${cleanPath}`, { method, headers, body: options.body === undefined ? undefined : JSON.stringify(options.body), signal: AbortSignal.timeout(15000) }); }
    catch (cause) { const e = new Error('Could not reach SwiftWash. Check your API URL, server, HTTPS, and CORS settings.'); e.cause = cause; throw e; }
    if (response.status === 204) return null;
    const payload = await response.json().catch(() => null);
    if (!response.ok) { if (response.status === 401) session(null); const details = payload?.details; const detailText = Array.isArray(details) ? details.map(d => `${d.field}: ${d.message}`).join(' ') : ''; fail([payload?.message || payload?.msg || `Request failed (${response.status}).`, detailText].filter(Boolean).join(' '), response.status, details); }
    return payload;
  },
  async login(email, password) { const result = await this.request('/auth/login', { method: 'POST', body: { email: email.trim(), password } }); session(result.user, result.token); return result; },
  async register(fields) { const result = await this.request('/auth/register', { method: 'POST', body: fields }); session(result.user, result.token); return result; },
  logout() { current = null; accessToken = null; remove(browserSession, KEYS.user); remove(browserSession, KEYS.token); },
  async restore() { if (settings.demo) { if (current) current = clone(data.users.find(u => u.id === current.id) || current); return this.user; } if (!accessToken) { session(null); return null; } const user = await this.request('/users/me'); session(user, accessToken); return this.user; },
  async listAll(path) { const rows = []; let page = 1; while (true) { const separator = path.includes('?') ? '&' : '?'; const result = await this.request(`${path}${separator}page=${page}&limit=100`); rows.push(...(result.data || [])); if (page >= (result.meta?.totalPages || 1)) return rows; page++; } },
  resetDemo() { data = seed(); persist(); if (settings.demo) session(clone(initialUser)); }
};
