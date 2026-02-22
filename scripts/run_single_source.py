#!/usr/bin/env python3
"""
Run a single source by ID with monitoring and cooling periods.
Usage: python3 run_single_source.py <source_id>
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

async def run_single_source(source_id: str):
    """Run a single source by ID."""
    print(f"Starting {source_id} scraper...")
    monitor_system()
    
    # Wait for cooling if needed
    wait_for_cooling()
    
    try:
        # Load registry to get source config
        import json
        with open('sources/registry.json', 'r') as f:
            registry = json.load(f)
        
        # Find the specific source
        source_config = None
        for source in registry['sources']:
            if source.get('id') == source_id:
                source_config = source
                break
        
        if not source_config:
            print(f"No source found with ID: {source_id}")
            print("Available source IDs:")
            for source in registry['sources']:
                print(f"  - {source.get('id')} ({source.get('name')})")
            return False
        
        print(f"Found source: {source_config['name']} ({source_config['language']})")
        
        # Run the scraper
        language = source_config['language']
        scraper = RegistryScraper(language, source_config)
        
        start_time = time.time()
        await scraper.run()
        end_time = time.time()
        
        print(f"Source {source_config['name']} completed in {end_time - start_time:.1f} seconds")
        monitor_system()
        
        print(f"\n{source_id} scraper completed successfully")
        
    except Exception as e:
        print(f"Error running {source_id} scraper: {e}")
        return False
    
    return True

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 run_single_source.py <source_id>")
        print("Example: python3 run_single_source.py ecmascript_spec")
        print("Example: python3 run_single_source.py mdn_web_apis")
        return
    
    source_id = sys.argv[1]
    
    print(f"Running {source_id} scraper individually...")
    print("This will run one source at a time to avoid performance issues.")
    
    # Run the scraper
    success = asyncio.run(run_single_source(source_id))
    
    if success:
        print(f"\n✅ {source_id} scraper completed successfully")
    else:
        print(f"\n❌ {source_id} scraper failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
