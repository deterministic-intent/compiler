# Sources Registry

This directory contains the source definitions for all programming languages and frameworks that will be scraped.

## Adding New Sources

To add a new source to the registry:

1. **Edit `registry.json`**: Add a new entry with the following structure:
   ```json
   {
     "language": "python",
     "name": "Python",
     "official_docs": [
       {
         "url": "https://docs.python.org/3/",
         "title": "Python 3 Documentation",
         "description": "Official Python 3 documentation"
       }
     ],
     "frameworks": [
       {
         "name": "Django",
         "url": "https://docs.djangoproject.com/",
         "description": "Django web framework documentation"
       }
     ]
   }
   ```

2. **Create language-specific scraper** (if needed):
   - Add a new file in `scraper/languages/` (e.g., `python_scraper.py`)
   - Inherit from `BaseScraper` and implement language-specific logic

3. **Add overrides** (optional):
   - Create a directory in `sources/overrides/` for the language
   - Add curated markdown files for stability

## Source Structure

Each source in the registry should include:

- **language**: The programming language identifier
- **name**: Human-readable name
- **official_docs**: Array of official documentation URLs
- **frameworks**: Array of framework documentation URLs
- **description**: Brief description of the language/ecosystem

## Best Practices

1. **Use official sources**: Always prefer official documentation over third-party sources
2. **Be respectful**: Follow robots.txt and implement rate limiting
3. **Test thoroughly**: Verify scrapers work before adding to production
4. **Keep updated**: Regularly check for changes in documentation structure
5. **Document changes**: Update this README when adding new sources
