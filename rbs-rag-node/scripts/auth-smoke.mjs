import jwt from 'jsonwebtoken';

const secret = process.env.RAG_ADMIN_JWT_SECRET || 'dev-secret';
const token = jwt.sign({ role: 'admin', tenant_id: 'admin' }, secret, { expiresIn: '1h' });
console.log(JSON.stringify({ token, secret }));
