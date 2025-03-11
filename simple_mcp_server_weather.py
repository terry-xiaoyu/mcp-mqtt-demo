import os, time
import requests
import mcp_over_mqtt as mcp

SERVER_NAME = "weather_tool"
VERSION = "0.1.0"

def get_weather(city_name):
    api_key = os.getenv("WEATHER_API_KEY", "")
    # HeWeather city lookup API to get the city's location ID
    location_url = f'https://geoapi.qweather.com/v2/city/lookup?location={city_name}&key={api_key}'
    location_response = requests.get(location_url)
    if location_response.status_code == 200:
        location_data = location_response.json()
        if location_data.get('code') == '200' and location_data.get('location'):
            location_id = location_data['location'][0]['id']
            # Use location ID to get real-time weather
            weather_url = f'https://devapi.qweather.com/v7/weather/now?location={location_id}&key={api_key}'
            weather_response = requests.get(weather_url)
            if weather_response.status_code == 200:
                weather_data = weather_response.json()
                if weather_data.get('code') == '200':
                    now = weather_data['now']
                    return {
                        "city": city_name,
                        "temperature": f"{now['temp']}°C",
                        "weather": now['text'],
                        "wind_direction": now['windDir'],
                        "wind_speed": f"{now['windSpeed']} km/h"
                    }
                else:
                    return f"Failed to get weather information: {weather_data.get('message')}"
            else:
                return f"Weather request failed, status code: {weather_response.status_code}"
        else:
            return f"Failed to get city ID: {location_data.get('message')}"
    else:
        return f"City lookup request failed, status code: {location_response.status_code}"

if __name__ == "__main__":
    supported_tools = [
        {
            "name": "get_weather",
            "description": "Get the real-time weather of the specified city",
            "parameters": {
                "type": "object",
                "properties": {
                    "city_name": {
                        "type": "string",
                        "description": "City name"
                    }
                }
            }
        }
    ]
    server_capabilities = {
        "tools": supported_tools
    }
    mcp.run_mcp_server(SERVER_NAME, VERSION, capabilities=server_capabilities,
                       tool_callbacks={"get_weather": get_weather})
    while True:
        time.sleep(100)
        pass
