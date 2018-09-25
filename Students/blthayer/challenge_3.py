########################################################################
# IMPORTS
# Standard library
from os.path import join
from multiprocessing import Process, Queue, JoinableQueue, cpu_count

# Installed
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

from sklearn.linear_model import Ridge, Lasso
from sklearn.metrics import mean_squared_error

########################################################################
# CONSTANTS
# In/out paths.
IN_DIR = join('..', '..', 'Challenges', '3Files')
OUT_DIR = '.'

# Input files.
TEST_FILE = join(IN_DIR, 'population_testing.csv')
TRAIN_FILE = join(IN_DIR, 'population_training.csv')

# Output files.
PRED_OUT = join(OUT_DIR, '3population_predicted.csv')
COEFF_OUT = join(OUT_DIR, '3parameters.csv')

# Random seed.
SEED = 42

# Maximum non-zero coefficients (how many other countries we're using
# as predictors)
COEFF_MAX = 5

# Initialize alphas for Lasso. This is terrible hard-coding, but hey, I
# had to add more as I went and copy + paste was easy :)
ALPHAS1 = 10 ** 10 * np.linspace(10, 0.1, 100)
ALPHAS2 = 10 ** 10 * np.linspace(100, 10,  100)
ALPHAS3 = 10 ** 10 * np.linspace(1000, 100, 100)
ALPHAS4 = 10 ** 10 * np.linspace(10000, 1000, 100)
ALPHAS5 = 10 ** 10 * np.linspace(100000, 10000, 100)
ALPHAS6 = 10 ** 10 * np.linspace(1000000, 100000, 100)

ALL_ALPHAS = [ALPHAS1, ALPHAS2, ALPHAS3, ALPHAS4, ALPHAS5, ALPHAS6]

# Iterations and tolerance for Lasso.
MAX_ITER = 100000
TOL = 0.01

# Use all processors
NUM_PROCESSES = cpu_count()

########################################################################
# FUNCTIONS


def lasso_for_alphas(alphas, x, y, x_test):
    """Loop over alphas and Lasso.

    NOTE: alphas should be in DESCENDING ORDER
    """
    # Track best score for this country.
    best_score = -np.inf

    # Initialize best_coefficients
    best_coeff = np.zeros(x.shape[1])

    # Initialize predictions.
    prediction = np.zeros(x_test.shape[0])

    # Track number of non-zero coefficients.
    non_zero_coeff_list = []

    # Loop over alphas and fit.
    for a in alphas:
        # Initialize a Lasso object
        lasso = Lasso(alpha=a, random_state=SEED, max_iter=MAX_ITER,
                      tol=TOL)

        # Fit.
        lasso.fit(x, y)

        # Extract these coefficients.
        c = lasso.coef_

        # Track coefficients if we have <= 5 "non-zero" elements.
        non_zero = ~np.isclose(c, 0)
        num_non_zero = np.count_nonzero(non_zero)

        non_zero_coeff_list.append(num_non_zero)

        # If we're below zero, track the minimum coefficients.
        if (num_non_zero <= COEFF_MAX) and (num_non_zero > 0):

            # Score.
            r2 = lasso.score(x, y)

            # If this score is the best, we'll track the coefficients,
            # and create a prediction.
            if r2 > best_score:
                # Ensure values that were close to 0 are exactly 0.
                c[~non_zero] = 0

                # Put c into coeff.
                best_coeff = c

                # Track the training score.
                best_score = r2

                # Predict.
                prediction = lasso.predict(X=x_test)

        elif num_non_zero >= COEFF_MAX:
            # Since we're looping in DESCENDING ORDER, we should break
            # the loop here. If the highest value of alpha gives us
            # too many coefficients, no sense in going to smaller alpha
            # values.
            break

        elif num_non_zero <= 0:
            # Our value of alpha is too high. Continue looping.
            continue

        else:
            # What's going on?
            raise UserWarning('WTF?')

    return best_score, best_coeff, prediction, non_zero_coeff_list


def fit_for_country(train_mat, test_mat, other_countries):
    """Call scores, coefficients, and predictions for a given country.
    """
    # Extract x and y
    x = train_mat[:, other_countries]
    y = train_mat[:, ~other_countries]
    x_test = test_mat[:, other_countries]

    for alphas in ALL_ALPHAS:
        s, c, p, non_zero_coeff = lasso_for_alphas(alphas=alphas, x=x, y=y,
                                                   x_test=x_test)

        # If we have a score that isn't negative infinity, we're done.
        if ~np.isneginf(s):
            break

    # If it happened again, better mention it.
    if np.isneginf(s):
        print('Failure for country {}.'.format(np.argwhere(~other_countries)))

    return s, c, p


def fit_for_country_worker(train_mat, test_mat, queue_in, queue_out):
    """Function for parallel worker"""

    while True:
        # Grab country information from the queue.
        i, num_countries = queue_in.get()

        # Initialize boolean for country indexing.
        other_countries = np.ones(num_countries, dtype=np.bool_)

        # Do not include this country.
        other_countries[i] = False

        # Leave the function if None is put in the queue.
        if other_countries is None:
            return

        # Perform the fit.
        s, c, p = fit_for_country(train_mat, test_mat, other_countries)

        # Put the data in the output queue.
        queue_out.put((other_countries, s, c, p))

        # Mark the task as complete.
        queue_in.task_done()


def fit_for_all():
    """Main function to perform fit for all countries."""
    ####################################################################
    # Read files
    train_df = pd.read_csv(TRAIN_FILE, encoding='cp1252').dropna(axis=0)
    test_df = pd.read_csv(TEST_FILE, encoding='cp1252').dropna(axis=0)

    # The test_df has one extra country. Line up train and test.
    test_df = test_df.loc[train_df.index]

    # Get matrices.
    train_mat = train_df.drop(['Country Name'], axis=1).values.T.astype(int)
    test_mat = test_df.drop(['Country Name'], axis=1).values.T.astype(int)

    # Grab list and number of countries for convenience.
    countries = train_df['Country Name']
    num_countries = countries.shape[0]

    # Initialize queues for parallel processing.
    queue_in = JoinableQueue()
    queue_out = Queue()

    # Start processes.
    processes = []
    for i in range(NUM_PROCESSES):
        p = Process(target=fit_for_country_worker, args=(train_mat, test_mat,
                                                         queue_in, queue_out))
        p.start()
        processes.append(p)

    # Loop over all the countries (columns of the train matrix).
    for i in range(num_countries):
    #for i in range(NUM_PROCESSES):
        # Put boolean array in the queue.
        queue_in.put((i, num_countries))

    # Wait for processing to finish.
    queue_in.join()

    # Track coefficients.
    best_coeff = pd.DataFrame(0.0, columns=train_df['Country Name'],
                              index=train_df['Country Name'])

    # Track training scores.
    best_scores = pd.Series(0.0, index=train_df['Country Name'])

    # Track predictions.
    predictions = pd.DataFrame(0.0,
                               columns=test_df.columns.drop('Country Name'),
                               index=test_df['Country Name'])

    # Map data.
    for _ in range(num_countries):
    #for _ in range(NUM_PROCESSES):
        # Grab data from the queue.
        other_countries, s, c, p = queue_out.get()

        country = countries[~other_countries].values[0]

        # Map.
        best_scores.loc[~other_countries] = s
        best_coeff.loc[other_countries, country] = c
        predictions.loc[~other_countries, :] = p

    # Shut down processes.
    for p in processes:
        queue_in.put_nowait(None)
        p.terminate()

    # Save coefficients and predictions to file.
    predictions.to_csv(PRED_OUT)
    best_coeff.to_csv(COEFF_OUT, index_label='Country')

    # Print training scores.
    # TODO: Add prediction scores.
    print('Summary of best R^2 scores:')
    print(best_scores.describe())

########################################################################
# MAIN


if __name__ == '__main__':
    fit_for_all()
