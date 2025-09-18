#!/usr/bin/env python3
import requests
import json
from difflib import SequenceMatcher
import sys

def get_nfl_teams():
    """Fetch NFL teams data from ESPN API"""
    url = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching data: {e}")
        return None

def similarity(a, b):
    """Calculate similarity between two strings"""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def find_team_id(search_term, teams_data):
    """Find team ID using fuzzy search"""
    if not teams_data or 'sports' not in teams_data:
        return None

    teams = teams_data['sports'][0]['leagues'][0]['teams']
    best_match = None
    best_score = 0

    for team in teams:
        team_info = team['team']

        # Search fields to match against
        search_fields = [
            team_info.get('displayName', ''),
            team_info.get('shortDisplayName', ''),
            team_info.get('name', ''),
            team_info.get('location', ''),
            team_info.get('abbreviation', ''),
            team_info.get('slug', '')
        ]

        # Find best match among all fields
        for field in search_fields:
            if field:
                score = similarity(search_term, field)
                if score > best_score:
                    best_score = score
                    best_match = {
                        'id': team_info['id'],
                        'name': team_info['displayName'],
                        'abbreviation': team_info['abbreviation'],
                        'location': team_info['location'],
                        'score': score
                    }

    return best_match if best_score > 0.3 else None

def main():
    if len(sys.argv) != 2:
        print("Usage: python nfl_team_finder.py <search_term>")
        print("Example: python nfl_team_finder.py bills")
        sys.exit(1)

    search_term = sys.argv[1]

    # Fetch teams data
    teams_data = get_nfl_teams()
    if not teams_data:
        print("Failed to fetch NFL teams data")
        sys.exit(1)

    # Find team
    result = find_team_id(search_term, teams_data)

    if result:
        print(f"Team ID: {result['id']}")
        print(f"Team: {result['name']}")
        print(f"Abbreviation: {result['abbreviation']}")
        print(f"Match confidence: {result['score']:.2f}")
    else:
        print(f"No team found matching '{search_term}'")
        sys.exit(1)

if __name__ == "__main__":
    main()