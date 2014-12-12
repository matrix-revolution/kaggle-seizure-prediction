"""Module for doing the training of the models."""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import logging

import sklearn
import sklearn.linear_model
import sklearn.svm
import sklearn.ensemble
import sklearn.metrics
from sklearn import cross_validation
from sklearn.grid_search import GridSearchCV
import pandas as pd
import numpy as np

from ..datasets import dataset


def get_model_class(method):
    if method == 'logistic':
        return sklearn.linear_model.LogisticRegression
    elif method == 'svm':
        return sklearn.svm.SVC
    elif method == 'mirowski-svm':
        return sklearn.svm.SVC
    elif method == 'sgd':
        return sklearn.linear_model.SGDClassifier
    elif method == 'random-forest':
        return sklearn.ensemble.RandomForestClassifier
    elif method == 'nearest-centroid':
        return sklearn.neighbors.NearestCentroid
    elif method == 'knn':
        return sklearn.neighbors.KNeighborsClassifier
    elif method == 'bagging':
        return sklearn.ensemble.BaggingClassifier
    else:
        raise NotImplementedError("Method {} is not supported".format(method))


def get_model(method, training_data_x, training_data_y, model_params=None, random_state=None):
    """
    Returns a dictionary with the model and cross-validation parameter grid for the model named *method*.
    """
    param_grid = dict()  ## This is the parameter grid which the grid search will go over

    min_c = sklearn.svm.l1_min_c(training_data_x, training_data_y, loss='log')

    if method == 'logistic':
        clf = sklearn.linear_model.LogisticRegression(C=1, random_state=random_state)
        param_grid = {'C': np.linspace(min_c, 1e5, 10), 'penalty': ['l1', 'l2'], 'random_state':[random_state]}

    elif method == 'svm':
        clf = sklearn.svm.SVC(probability=True, class_weight='auto', cache_size=1000)
        param_grid = [{'kernel': ['rbf'], 'gamma': [0, 1e-1, 1e-3],
                       'C': np.linspace(min_c, 1000, 3)}]

    elif method == 'mirowski-svm':
        clf = sklearn.svm.SVC(probability=True, class_weight='auto')
        # Below are the parameters used by Mirowski et.al
        # param_grid =  [{'kernel': ['rbf'], 'C': [min_c, 2**3, 2**6, 2**9],
        #                 'gamma': [2**(-13), 2**(-7), 0.5]}]
        # Fine-tuning based on the paramters found above
        param_grid = [{'kernel': ['rbf'], 'C': 64*np.linspace(1/4, 4, 4),
                       'gamma': 0.0001220703125 * np.linspace(1/4, 4, 4)}]

    elif method == 'sgd':
        clf = sklearn.linear_model.SGDClassifier()
        param_grid = [{'loss' : ['hinge', 'log'],
                       'penalty' : ['l1', 'l2', 'elasticnet'],
                       'alpha' : [0.0001, 0.001, 0.01, 0.1]}]

    elif method == 'random-forest':
        clf = sklearn.ensemble.RandomForestClassifier()
        param_grid = [{'max_features': ['sqrt', 'log2'],
                       'n_estimators': [10, 100, 1000],
                       'criterion': ['gini', 'entropy']}]

    elif method == 'nearest-centroid':
        clf = sklearn.neighbors.NearestCentroid()
        param_grid = [{'shrink_threshold': None},
                      {'shrink_threshold': np.linspace(0, 2, 10)}]

    elif method == 'knn':
        clf = sklearn.neighbors.KNeighborsClassifier()
        param_grid = [{'algorithm': ['ball_tree', 'kd_tree', 'brute'],
                       'n_neighbors': range(1, 5)}]

    elif method == 'bagging':
        base = sklearn.svm.SVC(
            probability=False, class_weight='auto', cache_size=1000,
            kernel='rbf', C=500, random_state=random_state)
        if model_params is not None:
            model_params['base_estimator'] = base
            if 'max_samples' not in model_params:
                model_params['max_samples'] = 0.5

        clf = sklearn.ensemble.BaggingClassifier(
            base_estimator=base)
        param_grid = [{'n_estimators': [10, 20],
                       'bootstrap_features': [True, False]}]

    else:
        raise NotImplementedError("Method {} is not supported".format(method))

    # Model params overrides the default param_grid
    if model_params is not None:
        param_grid = model_params

    return dict(estimator=clf, param_grid=param_grid)


def get_cv_generator(training_data, do_segment_split=True, random_state=None):
    """
    Returns a cross-validation generator.
    """
    k_fold_kwargs = dict(n_folds=10, random_state=random_state)
    if do_segment_split:
        cv = dataset.SegmentCrossValidator(training_data, cross_validation.StratifiedKFold, **k_fold_kwargs)
    else:
        cv = sklearn.cross_validation.StratifiedKFold(training_data['Preictal'], **k_fold_kwargs)
    return cv


def train_model(interictal,
                preictal,
                method='logistic',
                training_ratio=0.8,
                do_segment_split=True,
                processes=1,
                cv_verbosity=2,
                model_params=None,
                random_state=None,
                no_crossvalidation=False):
    """
    Trains a model on the provided data. If requested it will perform cross-validation experiments on the data
    and report performance measurements.
    :param interictal: A dataframe containing the interictal data
    :param preictal: A dataframe containing the interictal data
    :param method: A String describing the method to be used. See function get_model_class for valid values.
    :param training_ratio: The ratio of the data that will be used for the training set
    :param do_segment_split: Do the cross-validation split by segment
    :param processes: Number of processes to use for the cross-validation experiments.
    :param cv_verbosity: The verbosity level for the cross-validation experiments
    :param model_params: A dict containing the parameters to be passed to the model
    :param random_state: Seed
    :param no_crossvalidation: Do not perform cross-validation
    :return: A trained classfier model.
    """
    if random_state is not None:
        np.random.seed(random_state)

    if no_crossvalidation:
        clf_class = get_model_class(method=method)
        clf = clf_class()
        if model_params is not None:
            clf.set_params(**model_params)
        training_data = dataset.merge_interictal_preictal(interictal, preictal)
        training_x = training_data.drop('Preictal', axis=1)
        training_y = training_data['Preictal']

        logging.info("Fitting data to a {} model".format(method))
        clf.fit(training_x, training_y)
    else:
        training_data, test_data = dataset.split_experiment_data(interictal,
                                                             preictal,
                                                             training_ratio=training_ratio,
                                                             do_segment_split=do_segment_split,
                                                             random_state=random_state)
        logging.info("Shapes after splitting experiment data:")
        logging.info("training_data: {}".format(training_data.shape))
        logging.info("test_data: {}".format(test_data.shape))

        test_data_x = test_data.drop('Preictal', axis=1)
        test_data_y = test_data['Preictal']

        clf = select_model(training_data, method=method,
                           do_segment_split=do_segment_split,
                           processes=processes,
                           cv_verbosity=cv_verbosity,
                           model_params=model_params,
                           random_state=random_state)

        report = get_report(clf, test_data_x, test_data_y)
        logging.info(report)

    return clf


def refit_model(interictal, preictal, clf):
    """ Fits the classifier *clf* to the given preictal and interictal data. """

    training_data = dataset.merge_interictal_preictal(interictal, preictal)
    if hasattr(clf, 'best_estimator_'):
        return clf.best_estimator_.fit(training_data.drop('Preictal', axis=1), training_data['Preictal'])
    else:
        return clf.fit(training_data.drop('Preictal', axis=1), training_data['Preictal'])



def predict(clf, test_data, probabilities=True):
    """
    Returns an array of predictions for the given *test_data* using the classifier *clf*. If *probabilities* is True
    and the classifier supports it, the predictions will be Preictal probabilites.
    Otherwise, the class labels are used.
    """
    if probabilities and hasattr(clf, 'predict_proba'):
        predictions = clf.predict_proba(test_data)
        # The predictions from predict_proba is a k-dimensional array, with k
        # the number of classes. We want to take the column corresponding to the
        # class with the label 1
        if hasattr(clf, 'best_estimator_'):
            classes = clf.best_estimator_.classes_
        else:
            classes = clf.classes_
        class_index = list(classes).index(1)
        predictions = predictions[:, class_index]
    else:
        predictions = clf.predict(test_data)
    return predictions


def get_report(clf, test_data_x, test_data_y):
    """
    Returns a string with a report of how the classifier *clf* does on the test data.
    """
    test_data_y_pred = predict(clf, test_data_x, probabilities=False)

    report_lines = [
        "Classification report:",
        "Best parameters set found on development set:",
        "",
        str(clf.best_estimator_),
        "",
        grid_scores(clf),
        "Detailed classification report:",
        ""
        "The model is trained on the full development set.",
        "The scores are computed on the full evaluation set.",
        "",
        sklearn.metrics.classification_report(test_data_y, test_data_y_pred),
        "",
        cm_report(sklearn.metrics.confusion_matrix(test_data_y, test_data_y_pred),
                  labels=['Interictal', 'Preictal']),
        "",
    ]
    report = '\n'.join(report_lines)
    return report


def grid_scores(clf):
    """Returns a string with the grid scores"""
    score_lines = ["Grid scores on development set:", ""]
    for params, mean_score, scores in clf.grid_scores_:
        score_lines.append("{:0.3f} (+/-{:0.03f}) for {}".format(mean_score, scores.std()/2, params))

    score_lines.append("")
    return '\n'.join(score_lines)


def select_model(training_data, method='logistic',
                 do_segment_split=True,
                 processes=1,
                 cv_verbosity=2,
                 model_params=None,
                 random_state=None):
    """Fits a model given by *method* to the training data."""
    logging.info("Training a {} model".format(method))

    training_data_x = training_data.drop('Preictal', axis=1)
    training_data_y = training_data['Preictal']

    cv = get_cv_generator(training_data, do_segment_split=do_segment_split, random_state=random_state)

    scorer = sklearn.metrics.make_scorer(sklearn.metrics.roc_auc_score, average='weighted')
    model_dict = get_model(method,
                           training_data_x,
                           training_data_y,
                           model_params=model_params,
                           random_state=random_state)
    common_cv_kwargs = dict(cv=cv,
                            scoring=scorer,
                            n_jobs=processes,
                            pre_dispatch='2*n_jobs',
                            refit=True,
                            verbose=cv_verbosity,
                            iid=False)

    cv_kwargs = dict(common_cv_kwargs)
    cv_kwargs.update(model_dict)

    logging.info("Running grid search using the parameters: {}".format(model_dict))
    clf = GridSearchCV(**cv_kwargs)
    clf.fit(training_data_x, training_data_y)

    return clf


def preictal_ratio(predictions):
    """Returns the ratio of 'Preictal' occurrences in the dataframe *predictions*"""
    is_preictal = predictions == 'Preictal'  # A dataframe with Bools in the class column
    assert isinstance(is_preictal, pd.DataFrame)
    return is_preictal.sum() / is_preictal.count()


def assign_segment_scores(test_data, clf):
    """
    Returns a data frame with the segments of *test_data* as indices
    and the ratio of preictal guesses as a 'Preictal' column
    """
    predictions = predict(clf, test_data)
    df_predictions = pd.DataFrame(predictions,
                                  index=test_data.index,
                                  columns=('Preictal',)) # TODO Capital P here?
    segment_groups = df_predictions.groupby(level='segment')
    return segment_groups.mean()


def cm_report(cm, labels, sep='\t'):
    """Returns a pretty print for the confusion matrix"""
    columnwidth = max([len(x) for x in labels])
    cm_lines = ["Colums show what the true values(rows) were classified as."]

    # The following is used to output each cell of the table. By passing a keyword argument 'format' to the string
    # format function, the format of the output value can be set
    cell = "{:{format}}"
    names_format = "<{}".format(columnwidth)  # The names are left-justified
    col_format = ">{}".format(columnwidth)  # The columns are right formatted

    # Create the header string
    header_cells = [cell.format(label, format=col_format) for label in [""]+labels]
    header = sep.join(header_cells)
    cm_lines.append(header)

    # Print rows
    for i, label in enumerate(labels):
        row = []
        # This will be the label for the row
        row_label = cell.format(label, format=names_format)
        row.append(row_label)

        # The matrix cells are created as a list of strings
        cells = [cell.format(cm[i, j], format=col_format) for j in range(len(labels))]
        row.extend(cells)

        row_string = sep.join(row)
        cm_lines.append(row_string)

    return '\n'.join(cm_lines)