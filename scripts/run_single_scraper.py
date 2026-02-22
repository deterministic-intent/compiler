#!/usr/bin/env python3
"""
Run a single scraper with monitoring and cooling periods.
Usage: python3 run_single_scraper.py <language>
"""

import sys
import asyncio
import time
import psutil
from pathlib import Path

# Import the proper registry scraper
from scraper.run_scrapers import RegistryScraper

def get_cpu_temp():
    """Get CPU temperature if available."""
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            temp = int(f.read().strip()) / 1000.0
            return temp
    except:
        return None

def monitor_system():
    """Monitor system resources."""
    cpu_percent = psutil.cpu_percent(interval=1)
    memory = psutil.virtual_memory()
    temp = get_cpu_temp()
    
    print(f"CPU: {cpu_percent:.1f}% | RAM: {memory.percent:.1f}% | Temp: {temp:.1f}°C" if temp else f"CPU: {cpu_percent:.1f}% | RAM: {memory.percent:.1f}%")

def wait_for_cooling(target_temp=70.0, max_wait=300):
    """Wait for CPU to cool down."""
    start_time = time.time()
    while time.time() - start_time < max_wait:
        temp = get_cpu_temp()
        if temp and temp > target_temp:
            print(f"CPU hot ({temp:.1f}°C), cooling...")
            time.sleep(10)
            monitor_system()
        else:
            break

async def run_scraper(language: str):
    """Run a single scraper."""
    print(f"Starting {language} scraper...")
    monitor_system()
    
    # Wait for cooling if needed
    wait_for_cooling()
    
    try:
        # Load registry to get source config
        import json
        with open('sources/registry.json', 'r') as f:
            registry = json.load(f)
        
        # Find sources for this language
        language_sources = [
            source for source in registry['sources'] 
            if source.get('language') == language
        ]
        
        if not language_sources:
            print(f"No sources found for language: {language}")
            return False
        
        print(f"Found {len(language_sources)} sources for {language}")
        
        # Run each source using RegistryScraper
        for source_config in language_sources:
            print(f"Processing source: {source_config['name']}")
            
            scraper = RegistryScraper(language, source_config)
            
            # Run the scraper
            start_time = time.time()
            await scraper.run()
            end_time = time.time()
            
            print(f"Source {source_config['name']} completed in {end_time - start_time:.1f} seconds")
            monitor_system()
            
            # Cool down between sources
            print("Cooling down between sources...")
            time.sleep(5)
        
        print(f"\n{language} scraper completed successfully")
        
    except Exception as e:
        print(f"Error running {language} scraper: {e}")
        return False
    
    return True

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 run_single_scraper.py <language>")
        print("Available languages: python, javascript, typescript, java, go, rust, c, cpp, php, ruby, swift, kotlin, solidity, bash, sql, html")
        return
    
    language = sys.argv[1].lower()
    
    print(f"Running {language} scraper individually...")
    print("This will run one scraper at a time to avoid performance issues.")
    
    # Run the scraper
    success = asyncio.run(run_scraper(language))
    
    if success:
        print(f"\n✅ {language} scraper completed successfully")
    else:
        print(f"\n❌ {language} scraper failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
