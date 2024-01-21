import argparse
from concurrent import futures
import grpc
import logging
import time

import tetra3_pb2
import tetra3_pb2_grpc

import tetra3


class Tetra3Servicer(tetra3_pb2_grpc.Tetra3Servicer):
    def __init__(self, filename):
        self._tetra3 = tetra3.Tetra3(load_database=filename)
        self._logger = logging.getLogger('tetra3.Tetra3')

    def SolveFromCentroids(self, request, context):
        start = time.perf_counter()

        # Convert the request fields for call to Tetra3 solve_from_centroids()
        # function.
        star_centroids = []
        for sc in request.star_centroids:
            star_centroids.append((sc.y, sc.x))

        size = (request.image_height, request.image_width)

        fov_estimate = None
        if request.HasField('fov_estimate'):
            fov_estimate = request.fov_estimate

        fov_max_error = None
        if request.HasField('fov_max_error'):
            fov_max_error = request.fov_max_error

        match_radius = 0.01
        if request.HasField('match_radius'):
            match_radius = request.match_radius

        match_threshold = 1e-3
        if request.HasField('match_threshold'):
            match_threshold = request.match_threshold

        solve_timeout_ms = None
        if request.HasField('solve_timeout'):
            st = request.solve_timeout
            timeout = st.seconds + st.nanos / 1000000000
            solve_timeout_ms = timeout * 1000

        target_pixel = []
        for tp in request.target_pixels:
            target_pixel.append((tp.y, tp.x))
        if len(target_pixel) == 0:
            target_pixel = None

        distortion = None
        if request.HasField('distortion'):
            distortion = request.distortion

        return_matches = request.return_matches

        match_max_error = None
        if request.HasField('match_max_error'):
            match_max_error = request.match_max_error

        failure_reason = None
        if len(star_centroids) < 4:
            failure_reason = 'Too few centroids, got %d but need at least 4' % len(star_centroids)
            result_dict = {}
        else:
            # Process the request
            result_dict = self._tetra3.solve_from_centroids(
                star_centroids, size,
                fov_estimate=fov_estimate,
                fov_max_error=fov_max_error,
                match_radius=match_radius,
                match_threshold=match_threshold,
                solve_timeout=solve_timeout_ms,
                target_pixel=target_pixel,
                distortion=distortion,
                return_matches=return_matches,
                return_visual=False,
                match_max_error=match_max_error)

        result = tetra3_pb2.SolveResult()
        # Populate result proto from Tetra3 result dict.
        ra = result_dict.get('RA', None)
        dec = result_dict.get('Dec', None)
        roll = result_dict.get('Roll', None)
        fov = result_dict.get('FOV', None)
        distortion = result_dict.get('distortion', None)
        rmse = result_dict.get('RMSE', None)
        matches = result_dict.get('Matches', None)
        prob = result_dict.get('Prob', None)
        epoch_equinox = result_dict.get('epoch_equinox', None)
        epoch_proper_motion = result_dict.get('epoch_proper_motion', None)
        cache_hit_fraction = result_dict.get('cache_hit_fraction', None)
        ra_list = result_dict.get('RA_target', None)
        dec_list = result_dict.get('Dec_target', None)
        matched_stars_list = result_dict.get('matched_stars', None)
        matched_centroids_list = result_dict.get('matched_centroids', None)
        matched_cat_id_list = result_dict.get('matched_catID', None)

        if failure_reason is None and ra is None:
            # TODO(smr): get more information from Tetra3 about solve failure:
            # * no pattern match
            # * pattern(s) match, but verification fails
            # what else?
            failure_reason = 'Tetra3 solve failure'

        if ra is not None:
            result.image_center_coords.ra = ra
        if dec is not None:
            result.image_center_coords.dec = dec
        if roll is not None:
            result.roll = roll
        if fov is not None:
            result.fov = fov
        if distortion is not None:
            result.distortion = distortion
        if rmse is not None:
            result.rmse = rmse
        if matches is not None:
            result.matches = matches
        if prob is not None:
            result.prob = prob
        if epoch_equinox is not None:
            result.epoch_equinox = epoch_equinox
        if epoch_proper_motion is not None:
            result.epoch_proper_motion = epoch_proper_motion
        if cache_hit_fraction is not None:
            result.cache_hit_fraction = cache_hit_fraction

        if ra_list is not None:
            assert dec_list is not None
            if len(target_pixel) == 1:
                ra_list = [ra_list]
                dec_list = [dec_list]
            assert len(ra_list) == len(dec_list)
            for i in range(len(ra_list)):
                target_coord = result.target_coords.add()
                target_coord.ra = ra_list[i]
                target_coord.dec = dec_list[i]

        if matched_stars_list is not None:
            assert matched_centroids_list is not None
            assert len(matched_stars_list) == len(matched_centroids_list)
            if matched_cat_id_list is not None:
                assert len(matched_stars_list) == len(matched_cat_id_list)
            for i in range(len(matched_stars_list)):
                matched_star = result.matched_stars.add()
                matched_star.celestial_coord.ra = matched_stars_list[i][0]
                matched_star.celestial_coord.dec = matched_stars_list[i][1]
                matched_star.magnitude = matched_stars_list[i][2]
                matched_star.image_coord.y = matched_centroids_list[i][0]
                matched_star.image_coord.x = matched_centroids_list[i][1]
                if matched_cat_id_list is not None:
                    matched_star.cat_id = '%s' % matched_cat_id_list[i]

        elapsed = time.perf_counter() - start
        result.solve_time.seconds = int(elapsed)
        elapsed_frac = elapsed - int(elapsed)
        result.solve_time.nanos = int(elapsed_frac * 1000000000)
        if failure_reason is not None:
            result.failure_reason = failure_reason

        return result


def startServer():
    ap = argparse.ArgumentParser(
        description='Runs gRPC server to plate-solve a list of star locations in ' \
        'an image to the celestial coordinates of the image.')
    ap.add_argument('-a', '--address', default='unix:///home/pi/tetra3.sock',
                    help='address to listen on')
    ap.add_argument('filename', help='name of database file in tetra3/data directory')
    args = ap.parse_args()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    tetra3_pb2_grpc.add_Tetra3Servicer_to_server(Tetra3Servicer(args.filename), server)
    server.add_insecure_port(args.address)
    server.start()
    server.wait_for_termination()


if __name__ == '__main__':
    startServer()
