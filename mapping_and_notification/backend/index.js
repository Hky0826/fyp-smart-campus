require('dotenv').config();
const express = require('express');
const cors = require('cors');
const path = require('path');
const fs = require('fs');

const authRoutes = require('./routes/authRoutes');
const mapRoutes = require('./routes/mapRoutes');
const engineRoutes = require('./routes/engineRoutes');
const notificationRoutes = require('./routes/notificationRoutes');
const { connectBroker } = require('./utils/mqBroker');

const app = express();
app.use(cors());
app.use(express.json());

// Serve static uploads
const uploadDir = path.join(__dirname, 'uploads');
if (!fs.existsSync(uploadDir)) fs.mkdirSync(uploadDir);
app.use('/uploads', express.static(uploadDir));

// Mount Modular Routes (at both / and /api for direct and reverse-proxy access)
app.get('/health', (req, res) => res.json({ status: 'healthy', service: 'mapping-and-notification-microservice' }));
app.get('/api/health', (req, res) => res.json({ status: 'healthy', service: 'mapping-and-notification-microservice' }));

app.use('/', authRoutes);
app.use('/', mapRoutes);
app.use('/', engineRoutes);
app.use('/', notificationRoutes);

app.use('/api', authRoutes);
app.use('/api', mapRoutes);
app.use('/api', engineRoutes);
app.use('/api', notificationRoutes);

const PORT = 5000;
app.listen(PORT, () => {
    console.log(`Server is running on http://localhost:${PORT}`);
    // Connect to RabbitMQ asynchronously on startup
    connectBroker().catch(err => console.error('[RabbitMQ] Connection startup failed:', err.message));
});