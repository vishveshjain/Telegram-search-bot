# Telegram Search Bot Website

A modern, responsive website for the Telegram Search Bot that allows users to search across Telegram groups and channels.

## Features

- Modern and trendy UI/UX design
- Responsive layout for all device sizes
- Dark/light mode toggle
- Search functionality
- Trending topics section
- Feature showcase
- Step-by-step guide

## File Structure

```
website/
├── css/
│   └── style.css
├── js/
│   └── main.js
├── index.html
├── README.md
├── CONTRIBUTING.md
└── LICENSE
```

## Setup and Deployment

### Local Development

1. Clone this repository
2. Install Python dependencies:
   ```
   pip install -r requirements.txt
   pip install flask python-dotenv pymongo
   ```
3. Navigate to the `website` directory and start the Flask app:
   ```
   python app.py
   ```
4. Open http://localhost:5000 in your browser

### Deployment Options

#### Option 1: Traditional Web Hosting

1. Upload all files to your web hosting provider
2. Ensure the directory structure is maintained

#### Option 2: GitHub Pages

1. Push the website folder to a GitHub repository
2. Enable GitHub Pages in the repository settings

#### Option 3: Netlify/Vercel

1. Connect your repository to Netlify or Vercel
2. Configure build settings (not required for static sites)
3. Deploy

## Customization

### Bot Integration

To integrate with your Telegram bot:

1. Update the bot username in the links:
   ```html
   <a href="https://t.me/your_bot_username" class="btn primary-btn">
   ```

2. Implement the search functionality in `main.js` to connect with your bot's API

### Styling

- All styling is contained in `css/style.css`
- Color scheme can be modified by changing the CSS variables at the top of the file

## Browser Compatibility

- Chrome (latest)
- Firefox (latest)
- Safari (latest)
- Edge (latest)
- Opera (latest)

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on how to get started.

## License

This project is licensed under the Creative Commons Attribution-NonCommercial 4.0 International Public License. See the [LICENSE](LICENSE) file for details.

## Credits

- Font Awesome for icons
- Google Fonts for typography
- Responsive design using CSS Grid and Flexbox

## Screenshots

| Home | Search Results | Telegram Post Preview |
|------|---------------|----------------------|
| ![Home](screenshot-1.png) | ![Search Results](screenshot-2.png) | ![Telegram Post Preview](screenshot-3.png) |
