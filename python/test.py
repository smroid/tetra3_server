import argparse
import grpc
import logging
import time

import tetra3_pb2
import tetra3_pb2_grpc


def main():
    ap = argparse.ArgumentParser(description='Test gRPC client exercise plate-solver')
    ap.add_argument('-p', '--port', type=int, default=50051, help='port to connect to')
    args = ap.parse_args()

    logger = logging.getLogger('test')
    if not logger.hasHandlers():
        logger.setLevel(logging.DEBUG)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s:%(name)s-%(levelname)s: %(message)s')
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    # y,x
    centroids = [(616.895,  528.342), (433.709, 553.614), (581.358,  920.476),
                 (682.187,  474.311), (493.610, 465.951), (301.412,  581.112),
                 (125.019,  924.384), (736.228, 334.872), (734.000, 1001.650),
                 (459.419,  324.615), (358.651, 459.774), ( 34.464,   95.481),
                 (292.661,  714.715), ( 51.613, 853.937), (404.596,  400.519),
                 ( 38.560, 1013.460), (126.645, 534.583), (671.500,  678.626),
                 (147.357,   10.334), ( 32.093, 135.451), ( 35.331,  607.451),
                 (268.499,  574.395), (501.656, 639.474), (495.555,  269.554),
                 (555.537,  375.461), (628.456, 101.276)]
    request = tetra3_pb2.SolveRequest()
    for c in centroids:
        image_coord = request.star_centroids.add()
        image_coord.x = c[1]
        image_coord.y = c[0]
    request.image_width = 1024
    request.image_height = 768
    request.fov_estimate = 11
    # request.match_max_error = 0.005

    server_address = 'localhost:%d' % args.port
    with grpc.insecure_channel(server_address) as channel:
        stub = tetra3_pb2_grpc.Tetra3Stub(channel)

        # Do a first call to warm up the connection; add timing around a second call.
        discard = stub.SolveFromCentroids(request, timeout=10)

        start = time.perf_counter()
        response = stub.SolveFromCentroids(request, timeout=10)
        elapsed = time.perf_counter() - start

        print('Reponse: %s' % response)
        solve_time = response.solve_time.seconds + response.solve_time.nanos / 1000000000
        rpc_overhead = elapsed - solve_time
        print('Time total=solve+RPC %.2f=%.2f+%.2f ms' %
              (elapsed * 1000, solve_time * 1000, rpc_overhead * 1000))


if __name__ == "__main__":
    main()
