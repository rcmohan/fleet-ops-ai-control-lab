"""Small synthetic road networks, one per region, so simulated vehicles stay on land.

Nodes are real town and district locations; edges roughly follow highway corridors between
them. Edges marked as crossings (bridges and tunnels) are the only ones allowed over water,
and vehicles never park on them. tests/test_roads.py checks every node and every edge
against a land mask.
"""

from __future__ import annotations

import heapq
import math
import random
from dataclasses import dataclass, field

KM_PER_DEGREE = 111.0

LatLon = tuple[float, float]


def distance_km(a: LatLon, b: LatLon) -> float:
    dy = (b[0] - a[0]) * KM_PER_DEGREE
    dx = (b[1] - a[1]) * KM_PER_DEGREE * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dx, dy)


def lerp(a: LatLon, b: LatLon, t: float) -> LatLon:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


@dataclass(frozen=True)
class Edge:
    a: str
    b: str
    crossing: bool = False  # bridge or tunnel: may pass over water; nobody parks on it


@dataclass(frozen=True)
class Spot:
    """A point on the network: `t` of the way along edge `edge` from its `a` end."""

    edge: int
    t: float


@dataclass
class RoadNetwork:
    nodes: dict[str, LatLon]
    edges: list[Edge]
    adjacency: dict[str, list[tuple[str, float]]] = field(init=False)

    def __post_init__(self) -> None:
        self.adjacency = {name: [] for name in self.nodes}
        for edge in self.edges:
            length = distance_km(self.nodes[edge.a], self.nodes[edge.b])
            self.adjacency[edge.a].append((edge.b, length))
            self.adjacency[edge.b].append((edge.a, length))
        self.parking_edges = [i for i, edge in enumerate(self.edges) if not edge.crossing]

    def ends(self, spot: Spot) -> tuple[LatLon, LatLon]:
        edge = self.edges[spot.edge]
        return self.nodes[edge.a], self.nodes[edge.b]

    def point(self, spot: Spot) -> LatLon:
        return lerp(*self.ends(spot), spot.t)

    def random_spot(self, rng: random.Random) -> Spot:
        return Spot(rng.choice(self.parking_edges), rng.uniform(0.05, 0.95))

    def snap(self, position: LatLon) -> Spot:
        """The nearest parking point on the network (for positions saved before roads)."""
        best: tuple[float, Spot] | None = None
        for index in self.parking_edges:
            a, b = self.ends(Spot(index, 0.0))
            # Project in a local flat frame scaled to kilometres.
            scale = math.cos(math.radians(a[0]))
            ax, ay = a[1] * scale, a[0]
            bx, by = b[1] * scale, b[0]
            px, py = position[1] * scale, position[0]
            dx, dy = bx - ax, by - ay
            length2 = dx * dx + dy * dy
            t = 0.0 if length2 == 0 else ((px - ax) * dx + (py - ay) * dy) / length2
            t = min(0.95, max(0.05, t))
            gap = distance_km(position, lerp(a, b, t))
            if best is None or gap < best[0]:
                best = (gap, Spot(index, t))
        assert best is not None
        return best[1]

    def _shortest(self, start: dict[str, float]) -> tuple[dict[str, float], dict[str, str]]:
        distances = dict(start)
        previous: dict[str, str] = {}
        queue = [(cost, node) for node, cost in start.items()]
        heapq.heapify(queue)
        while queue:
            cost, node = heapq.heappop(queue)
            if cost > distances.get(node, math.inf):
                continue
            for neighbour, length in self.adjacency[node]:
                candidate = cost + length
                if candidate < distances.get(neighbour, math.inf):
                    distances[neighbour] = candidate
                    previous[neighbour] = node
                    heapq.heappush(queue, (candidate, neighbour))
        return distances, previous

    def route(self, origin: Spot, target: Spot) -> list[LatLon]:
        """Waypoints from the origin spot (exclusive) to the target spot (inclusive)."""
        goal = self.point(target)
        if origin.edge == target.edge:
            return [goal]
        here = self.point(origin)
        a, b = self.edges[origin.edge].a, self.edges[origin.edge].b
        distances, previous = self._shortest({
            a: distance_km(here, self.nodes[a]), b: distance_km(here, self.nodes[b]),
        })
        ta, tb = self.edges[target.edge].a, self.edges[target.edge].b
        last = min(
            (node for node in (ta, tb) if node in distances),
            key=lambda node: distances[node] + distance_km(self.nodes[node], goal),
            default=None,
        )
        if last is None:  # disconnected network; should not happen (tests check it)
            return [goal]
        path = [last]
        while path[-1] in previous:
            path.append(previous[path[-1]])
        return [self.nodes[node] for node in reversed(path)] + [goal]


def network(nodes: dict[str, LatLon], edges: str) -> RoadNetwork:
    """Edges as lines of `a b` or `a b crossing`."""
    parsed = []
    for line in edges.strip().splitlines():
        parts = line.split()
        parsed.append(Edge(parts[0], parts[1], len(parts) > 2 and parts[2] == "crossing"))
    return RoadNetwork(nodes, parsed)


NETWORKS: dict[str, RoadNetwork] = {
    "us-east": network(
        {
            "manhattan_downtown": (40.713, -74.006), "manhattan_midtown": (40.754, -73.984),
            "harlem": (40.809, -73.946), "bronx": (40.845, -73.865),
            "yonkers": (40.931, -73.899), "white_plains": (41.034, -73.763),
            "new_rochelle": (40.911, -73.782), "stamford": (41.053, -73.539),
            "long_island_city": (40.744, -73.948), "flushing": (40.758, -73.830),
            "jamaica": (40.702, -73.789), "brooklyn_downtown": (40.693, -73.990),
            "flatbush": (40.641, -73.959), "hempstead": (40.706, -73.619),
            "hicksville": (40.768, -73.525), "huntington": (40.855, -73.426),
            "staten_island": (40.582, -74.150), "jersey_city": (40.733, -74.063),
            "newark": (40.736, -74.172), "elizabeth": (40.664, -74.211),
            "paterson": (40.917, -74.172), "hackensack": (40.886, -74.043),
            "morristown": (40.797, -74.481), "woodbridge": (40.558, -74.285),
            "edison": (40.519, -74.412), "new_brunswick": (40.486, -74.452),
            "freehold": (40.260, -74.274),
        },
        """
        manhattan_downtown manhattan_midtown
        manhattan_midtown harlem
        harlem bronx crossing
        harlem yonkers
        yonkers white_plains
        bronx new_rochelle
        new_rochelle white_plains
        white_plains stamford
        bronx flushing crossing
        manhattan_midtown long_island_city crossing
        long_island_city flushing
        flushing jamaica
        jamaica hempstead
        hempstead hicksville
        hicksville huntington
        manhattan_downtown brooklyn_downtown crossing
        brooklyn_downtown flatbush
        brooklyn_downtown jamaica
        flatbush jamaica
        flatbush staten_island crossing
        staten_island elizabeth crossing
        staten_island woodbridge crossing
        manhattan_downtown jersey_city crossing
        manhattan_midtown hackensack crossing
        jersey_city newark crossing
        hackensack jersey_city
        hackensack paterson
        paterson newark
        newark elizabeth
        elizabeth woodbridge
        woodbridge edison
        edison new_brunswick
        edison freehold
        newark morristown
        morristown new_brunswick
        """,
    ),
    "us-central": network(
        {
            "loop": (41.881, -87.632), "lincoln_park": (41.921, -87.652),
            "evanston": (42.045, -87.688), "skokie": (42.034, -87.733),
            "northbrook": (42.128, -87.829), "waukegan": (42.360, -87.860),
            "ohare": (41.977, -87.836), "schaumburg": (42.033, -88.083),
            "elgin": (42.037, -88.281), "oak_park": (41.885, -87.784),
            "cicero": (41.845, -87.754), "midway": (41.786, -87.752),
            "hyde_park": (41.795, -87.600), "orland_park": (41.630, -87.854),
            "hammond": (41.583, -87.500), "gary": (41.580, -87.346),
            "naperville": (41.773, -88.148), "aurora": (41.760, -88.320),
            "joliet": (41.525, -88.082),
        },
        """
        loop lincoln_park
        lincoln_park evanston
        evanston skokie
        skokie northbrook
        northbrook waukegan
        skokie ohare
        ohare schaumburg
        schaumburg elgin
        ohare oak_park
        oak_park loop
        oak_park cicero
        cicero midway
        midway loop
        midway hyde_park
        hyde_park loop
        midway orland_park
        orland_park hammond
        hammond gary
        midway naperville
        naperville aurora
        naperville joliet
        joliet orland_park
        aurora elgin
        schaumburg naperville
        """,
    ),
    "us-west": network(
        {
            "sf_downtown": (37.787, -122.407), "sf_marina": (37.800, -122.437),
            "presidio": (37.800, -122.470), "sausalito": (37.858, -122.490),
            "san_rafael": (37.974, -122.531), "sf_sunset": (37.753, -122.480),
            "daly_city": (37.688, -122.470), "south_sf": (37.655, -122.420),
            "burlingame": (37.580, -122.360), "san_mateo": (37.563, -122.325),
            "redwood_city": (37.485, -122.236), "palo_alto": (37.443, -122.160),
            "mountain_view": (37.394, -122.081), "san_jose": (37.336, -121.891),
            "fremont": (37.548, -121.988), "hayward": (37.669, -122.081),
            "oakland": (37.804, -122.271), "berkeley": (37.871, -122.273),
            "richmond": (37.940, -122.340), "walnut_creek": (37.910, -122.065),
            "dublin": (37.702, -121.936), "livermore": (37.682, -121.768),
        },
        """
        sf_downtown sf_marina
        sf_marina presidio
        presidio sausalito crossing
        sausalito san_rafael crossing
        sf_downtown sf_sunset
        sf_sunset daly_city
        daly_city south_sf
        sf_downtown south_sf
        south_sf burlingame
        burlingame san_mateo
        san_mateo redwood_city
        redwood_city palo_alto
        palo_alto mountain_view
        mountain_view san_jose
        san_jose fremont
        fremont hayward
        hayward oakland
        sf_downtown oakland crossing
        oakland berkeley
        berkeley richmond
        richmond san_rafael crossing
        oakland walnut_creek
        walnut_creek dublin
        dublin livermore
        hayward dublin
        """,
    ),
    "us-south": network(
        {
            "downtown": (29.760, -95.369), "galleria": (29.739, -95.463),
            "katy": (29.786, -95.824), "cypress": (29.969, -95.697),
            "spring": (30.080, -95.417), "the_woodlands": (30.166, -95.461),
            "iah": (29.990, -95.336), "humble": (29.999, -95.262),
            "channelview": (29.776, -95.115), "baytown": (29.740, -94.977),
            "pasadena": (29.691, -95.209), "clear_lake": (29.565, -95.130),
            "league_city": (29.507, -95.095), "pearland": (29.564, -95.286),
            "sugar_land": (29.620, -95.635),
        },
        """
        downtown galleria
        galleria katy
        galleria sugar_land
        katy cypress
        cypress spring
        spring the_woodlands
        spring iah
        iah downtown
        iah humble
        downtown channelview
        channelview baytown crossing
        downtown pasadena
        pasadena clear_lake
        clear_lake league_city
        pasadena pearland
        downtown pearland
        pearland sugar_land
        """,
    ),
    "ca-east": network(
        {
            "downtown": (43.655, -79.385), "north_york": (43.768, -79.414),
            "scarborough": (43.773, -79.257), "etobicoke": (43.643, -79.565),
            "mississauga": (43.589, -79.644), "brampton": (43.686, -79.760),
            "vaughan": (43.836, -79.498), "richmond_hill": (43.882, -79.440),
            "markham": (43.857, -79.337), "pickering": (43.835, -79.089),
            "oshawa": (43.897, -78.865), "oakville": (43.470, -79.700),
            "burlington": (43.360, -79.820),
        },
        """
        downtown north_york
        downtown etobicoke
        etobicoke mississauga
        mississauga oakville
        oakville burlington
        mississauga brampton
        brampton vaughan
        vaughan richmond_hill
        richmond_hill markham
        north_york vaughan
        north_york richmond_hill
        north_york scarborough
        scarborough markham
        scarborough pickering
        pickering oshawa
        downtown scarborough
        """,
    ),
    "ca-west": network(
        {
            "downtown": (49.282, -123.120), "broadway": (49.262, -123.114),
            "east_van": (49.262, -123.069), "brentwood": (49.267, -123.000),
            "metrotown": (49.226, -122.999), "south_van": (49.220, -123.100),
            "richmond": (49.166, -123.137), "ladner": (49.089, -123.082),
            "new_westminster": (49.206, -122.911), "surrey": (49.189, -122.849),
            "langley": (49.104, -122.660), "coquitlam": (49.280, -122.800),
            "west_van": (49.327, -123.137), "north_van": (49.322, -123.073),
        },
        """
        downtown broadway crossing
        broadway east_van
        broadway south_van
        east_van brentwood
        east_van metrotown
        brentwood coquitlam
        coquitlam new_westminster
        metrotown new_westminster
        new_westminster surrey crossing
        surrey langley
        surrey ladner
        south_van richmond crossing
        richmond ladner crossing
        downtown west_van crossing
        west_van north_van
        brentwood north_van crossing
        """,
    ),
    "eu-west": network(
        {
            "city": (51.513, -0.090), "westminster": (51.499, -0.128),
            "camden": (51.539, -0.143), "islington": (51.536, -0.103),
            "stratford": (51.541, -0.003), "canary_wharf": (51.505, -0.020),
            "greenwich": (51.482, -0.008), "brixton": (51.462, -0.115),
            "clapham": (51.462, -0.138), "wimbledon": (51.421, -0.206),
            "croydon": (51.373, -0.099), "hammersmith": (51.492, -0.223),
            "ealing": (51.513, -0.305), "heathrow": (51.471, -0.452),
            "wembley": (51.556, -0.280), "harrow": (51.580, -0.336),
            "watford": (51.656, -0.390), "barnet": (51.652, -0.200),
            "enfield": (51.652, -0.081), "tottenham": (51.588, -0.071),
            "ilford": (51.559, 0.075), "romford": (51.575, 0.183),
            "bromley": (51.406, 0.015), "dartford": (51.446, 0.218),
            "kingston": (51.412, -0.300),
        },
        """
        city westminster crossing
        city islington
        islington camden
        camden westminster
        city stratford
        city canary_wharf
        canary_wharf stratford
        stratford ilford
        ilford romford
        canary_wharf greenwich crossing
        greenwich bromley
        greenwich dartford
        bromley croydon
        croydon brixton
        brixton clapham
        clapham wimbledon
        wimbledon kingston
        kingston hammersmith crossing
        hammersmith westminster
        hammersmith ealing
        ealing heathrow
        ealing wembley
        wembley harrow
        harrow watford
        wembley camden
        camden barnet
        barnet enfield
        enfield tottenham
        tottenham islington
        tottenham stratford
        city brixton crossing
        westminster clapham crossing
        """,
    ),
    "eu-central": network(
        {
            "innenstadt": (50.111, 8.682), "sachsenhausen": (50.100, 8.690),
            "airport": (50.038, 8.562), "offenbach": (50.100, 8.766),
            "hanau": (50.133, 8.917), "bad_homburg": (50.228, 8.618),
            "oberursel": (50.202, 8.577), "eschborn": (50.143, 8.570),
            "hoechst": (50.101, 8.543), "russelsheim": (49.995, 8.414),
            "wiesbaden": (50.078, 8.240), "mainz": (49.999, 8.273),
            "darmstadt": (49.873, 8.651), "langen": (49.993, 8.669),
            "bad_vilbel": (50.179, 8.737), "friedberg": (50.336, 8.755),
        },
        """
        innenstadt sachsenhausen crossing
        innenstadt eschborn
        eschborn oberursel
        oberursel bad_homburg
        bad_homburg friedberg
        innenstadt bad_vilbel
        bad_vilbel friedberg
        innenstadt hoechst
        hoechst wiesbaden
        wiesbaden mainz crossing
        mainz russelsheim crossing
        russelsheim airport
        airport sachsenhausen
        sachsenhausen offenbach
        offenbach hanau crossing
        sachsenhausen langen
        langen darmstadt
        airport langen
        """,
    ),
}
DEFAULT_NETWORK = "us-east"


def network_for(region: str) -> RoadNetwork:
    return NETWORKS.get(region, NETWORKS[DEFAULT_NETWORK])
