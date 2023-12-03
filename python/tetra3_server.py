import argparse
from concurrent import futures
import grpc

import tetra3_pb2 as pb2
import tetra3_pb2_grpc as pb2_grpc

import tetra3


class Tetra3Servicer(pb2_grpc.Tetra3Servicer):
    def __init__(self, filename):
        self._tetra3 = tetra3.Tetra3(load_database=filename)

    def SolveFromCentroids(self, request, context):
        # Pick up the RPC deadline.
        time_remaining = context.time_remaining()
        if time_remaining is None:
            time_remaining = 1.0
        print('time_remaining %s' % time_remaining)  # TEMPORARY
        print('request %s' % request)  # TEMPORARY

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

        pattern_checking_stars = 8
        if request.HasField('pattern_checking_stars'):
            pattern_checking_stars = request.pattern_checking_stars

        match_radius = 0.01
        if request.HasField('match_radius'):
            match_radius = request.match_radius

        match_threshold = 1e-3
        if request.HasField('match_threshold'):
            match_threshold = request.match_threshold

        solve_timeout_ms = time_remaining * 1000

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

        # Process the request
        result_dict = self._tetra3.solve_from_centroids(
            star_centroids, size,
            fov_estimate=fov_estimate,
            fov_max_error=fov_max_error,
            pattern_checking_stars=pattern_checking_stars,
            match_radius=match_radius,
            match_threshold=match_threshold,
            solve_timeout=solve_timeout_ms,
            target_pixel=target_pixel,
            distortion=distortion,
            return_matches=return_matches,
            return_visual=False,
            match_max_error=match_max_error)
        print('Tetra3 result %s' % result_dict)  # TEMPORARY

        # Convert to result proto.
        result = pb2.SolveResult()
        if result_dict['RA'] is not None:
            result.image_center_coords.ra = result_dict['RA']
        if result_dict['Dec'] is not None:
            result.image_center_coords.dec = result_dict['Dec']
        if result_dict['Roll'] is not None:
            result.roll = result_dict['Roll']
        if result_dict['FOV'] is not None:
            result.fov = result_dict['FOV']
        if result_dict['distortion'] is not None:
            result.distortion = result_dict['distortion']
        if result_dict['RMSE'] is not None:
            result.rmse = result_dict['RMSE']
        if result_dict['Matches'] is not None:
            result.matches = result_dict['Matches']
        if result_dict['Prob'] is not None:
            result.prob = result_dict['Prob']
        if result_dict['epoch_equinox'] is not None:
            result.epoch_equinox = result_dict['epoch_equinox']
        if result_dict['epoch_proper_motion'] is not None:
            result.epoch_proper_motion = result_dict['epoch_proper_motion']
        if result_dict['cache_hit_fraction'] is not None:
            result.cache_hit_fraction = result_dict['cache_hit_fraction']
        result.solve_time.seconds = result_dict['T_solve'] // 1000
        result.solve_time.nanos = (result_dict['T_solve'] % 1000) * 1000000
        if result_dict['RA_target'] is not None:
            ra_list = result_dict['RA_target']
            dec_list = result_dict['Dec_target']
            assert dec_list is not None
            assert len(ra_list) == len(dec_list)
            for i in range(len(ra_list)):
                target_coord = result.target_coords.add()
                target_coord.ra = ra_list[i]
                target_coord.dec = dec_list[i]
        if result_dict['matched_stars'] is not None:
            matched_stars_list = result_dict['matched_stars']
            matched_centroids_list = result_dict['matched_centroids']
            matched_cat_id_list = result_dict['matched_catID']
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

        print('result %s' % result)  # TEMPORARY
        return result


def serve():
    ap = argparse.ArgumentParser(
        description='Runs gRPC server to plate-solve a list of star locations in ' \
        'an image to the celestial coordinates of the image.')
    ap.add_argument('-p', '--port', type=int, default=50051, help='port to listen on')
    ap.add_argument('filename', help='name of database file in tetra3/data directory')
    args = ap.parse_args()

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb2_grpc.add_Tetra3Servicer_to_server(Tetra3Servicer(args.filename), server)
    server.add_insecure_port('[::]:%d' % args.port)
    server.start()
    server.wait_for_termination()


if __name__ == '__main__':
    serve()
