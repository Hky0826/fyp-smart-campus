/**
 * Middleware: API Key Authentication for the External Navigation Endpoint.
 * Validates the x-api-key request header against NAVIGATION_API_KEY in .env.
 */
const validateApiKey = (req, res, next) => {
    const providedKey = req.headers['x-api-key'];
    const validKey = process.env.NAVIGATION_API_KEY;

    if (!validKey) {
        console.error('NAVIGATION_API_KEY is not defined in the environment configuration.');
        return res.status(500).json({ message: 'Navigation service is not configured.' });
    }

    if (!providedKey || providedKey !== validKey) {
        return res.status(401).json({ message: 'Invalid or missing API key. Provide a valid x-api-key header.' });
    }

    next();
};

module.exports = { validateApiKey };
