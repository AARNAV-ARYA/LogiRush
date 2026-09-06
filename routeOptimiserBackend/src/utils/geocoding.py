# src/utils/geocoding.py
"""Geocoding utilities for route optimization."""

from haversine import haversine, Unit
import logging

logger = logging.getLogger(__name__)


class GeocodingUtils:
    """Utility class for geocoding and distance calculations."""

    @staticmethod
    def haversine_distance(coord1, coord2):
        """Calculate haversine distance between two coordinates.
        
        Args:
            coord1: Tuple of (latitude, longitude)
            coord2: Tuple of (latitude, longitude)
            
        Returns:
            Distance in kilometers
        """
        try:
            return haversine(coord1, coord2, unit=Unit.KILOMETERS)
        except Exception as e:
            logger.error(f"Error calculating haversine distance: {e}")
            return 0.0

    @staticmethod
    def get_node_coords(G, node):
        """Get coordinates of a node from the graph.
        
        Args:
            G: NetworkX graph
            node: Node identifier
            
        Returns:
            Tuple of (latitude, longitude) or None if not found
        """
        try:
            node_data = G.nodes[node]
            return (node_data.get('latitude'), node_data.get('longitude'))
        except Exception as e:
            logger.error(f"Error getting coordinates for node {node}: {e}")
            return None
